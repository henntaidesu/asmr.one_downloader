import os
import time
import requests
from PyQt6.QtCore import QThread, pyqtSignal
from src.read_conf import ReadConf
from src.download.re_title import sanitize_windows_filename, sanitize_folder_path
from src.download.download_utils import get_rj_number


class SpeedTooSlowException(Exception):
    """下载速度过慢异常"""
    pass


class DownloadThread(QThread):
    progress_updated = pyqtSignal(int, 'PyQt_PyObject', 'PyQt_PyObject', str)  # progress%, downloaded_bytes, total_bytes, status
    download_finished = pyqtSignal(str)  # work_id
    download_error = pyqtSignal(str, str)  # work_id, error_message
    speed_updated = pyqtSignal(str, float)  # work_id, speed_kb_s
    file_filter_stats = pyqtSignal('PyQt_PyObject', 'PyQt_PyObject', 'PyQt_PyObject', int, int)  # api_total, actual_total, skipped_total, total_files, skipped_files

    def __init__(self, work_id, work_detail, download_dir):
        super().__init__()
        self.work_id = str(work_id)
        self.work_detail = work_detail
        self.download_dir = download_dir
        self.is_paused = False
        self.is_cancelled = False
        self.downloaded_bytes = 0
        self.total_bytes = work_detail.get('total_size', 0)
        self.start_time = time.time()
        self.last_update_time = time.time()
        self.last_downloaded = 0

        # 读取速度限制配置 (MB/s)
        conf = ReadConf()
        download_conf = conf.read_download_conf()
        self.speed_limit_mbps = download_conf['speed_limit']  # MB/s
        self.speed_limit_bps = self.speed_limit_mbps * 1024 * 1024  # 转换为 bytes/s

        # 令牌桶算法参数
        self.bucket_size = self.speed_limit_bps  # 桶大小等于每秒允许的字节数
        self.tokens = self.bucket_size  # 初始令牌数
        self.last_refill_time = time.time()

        # 速度监控配置
        self.min_speed_kbps = download_conf['min_speed']  # KB/s，低于此速度需要重新下载
        self.min_speed_check_interval = download_conf['min_speed_check']  # 秒，速度检查间隔
        self.request_timeout = download_conf['timeout']  # 秒，请求超时时间
        
        # 速度监控状态
        self.speed_check_start_time = time.time()
        self.last_speed_check_time = time.time()
        self.current_speed_kbps = 0.0
        self.speed_check_enabled = True
        
        # 打印速度监控配置（用于调试）
        print(f"速度监控配置 - 最小速度: {self.min_speed_kbps} KB/s, 检查间隔: {self.min_speed_check_interval}秒, 超时: {self.request_timeout}秒")

    def refill_tokens(self):
        """补充令牌桶中的令牌"""
        if self.speed_limit_bps <= 0:
            return

        current_time = time.time()
        elapsed = current_time - self.last_refill_time

        # 根据时间补充令牌
        tokens_to_add = elapsed * self.speed_limit_bps
        self.tokens = min(self.bucket_size, self.tokens + tokens_to_add)
        self.last_refill_time = current_time

    def consume_tokens(self, bytes_needed):
        """消费令牌，如果令牌不足则等待"""
        if self.speed_limit_bps <= 0:
            return

        self.refill_tokens()

        if self.tokens >= bytes_needed:
            self.tokens -= bytes_needed
        else:
            # 计算需要等待的时间
            deficit = bytes_needed - self.tokens
            wait_time = deficit / self.speed_limit_bps
            time.sleep(wait_time)

            # 重新补充令牌并消费
            self.refill_tokens()
            self.tokens = max(0, self.tokens - bytes_needed)

    def run(self):
        try:
            self.download_files()
        except Exception as e:
            self.download_error.emit(self.work_id, str(e))

    def download_files(self):
        conf = ReadConf()
        proxy = conf.read_proxy_conf()

        if proxy['open_proxy']:
            proxy_url = {
                'http': f'{proxy["proxy_type"]}://{proxy["host"]}:{proxy["port"]}',
                'https': f'{proxy["proxy_type"]}://{proxy["host"]}:{proxy["port"]}'
            }
        else:
            proxy_url = None

        # 读取文件类型配置
        conf = ReadConf()
        selected_formats = conf.read_downfile_type()

        # 重新计算实际要下载的文件总大小（排除跳过的文件）
        actual_total_size = 0
        skipped_total_size = 0
        total_downloaded = 0
        total_files = len(self.work_detail['files'])
        skipped_files = 0

        for file_info in self.work_detail['files']:
            # 按照旧方法的逻辑进行文件类型筛选
            file_title = file_info['title']
            file_type = file_title[file_title.rfind('.') + 1:].upper()

            # 获取文件大小
            file_size = file_info.get('size', 0)
            if isinstance(file_size, str):
                try:
                    file_size = int(file_size)
                except ValueError:
                    file_size = 0

            if not selected_formats.get(file_type, False):
                # 跳过的文件，累计跳过大小和数量
                skipped_total_size += file_size
                skipped_files += 1
                continue

            # 需要下载的文件，累计到实际总大小
            actual_total_size += file_size

            filename = self.sanitize_filename(file_info['title'])
            # 保持API返回的目录结构，但根目录使用配置的命名方式
            folder_path = file_info.get('folder_path', '')
            if folder_path:
                # 清理文件夹路径
                clean_folder_path = self.sanitize_folder_path(folder_path)
                # 创建子文件夹
                subfolder_dir = os.path.join(self.download_dir, clean_folder_path)
                file_path = os.path.join(subfolder_dir, filename)
            else:
                file_path = os.path.join(self.download_dir, filename)

            # 标准化路径
            file_path = os.path.normpath(file_path)

            if os.path.exists(file_path):
                # 使用os.path.getsize获取实际文件大小，支持大文件
                downloaded_size = os.path.getsize(file_path)
                # 确保不超过文件实际大小
                downloaded_size = min(downloaded_size, file_size)
                total_downloaded += downloaded_size

        # 发送文件筛选统计信息到UI
        api_total_size = self.work_detail.get('total_size', 0)
        self.file_filter_stats.emit(api_total_size, actual_total_size, skipped_total_size, total_files, skipped_files)
        
        # 不发送初始进度更新，避免覆盖界面已显示的正确大小

        for file_info in self.work_detail['files']:
            if self.is_cancelled:
                return

            # 按照旧方法的逻辑进行文件类型筛选
            file_title = file_info['title']
            file_type = file_title[file_title.rfind('.') + 1:].upper()
            if not selected_formats.get(file_type, False):
                print(f"跳过文件: {file_title}")
                continue

            file_size = file_info['size']
            download_url = file_info['download_url']
            filename = self.sanitize_filename(file_info['title'])
            
            # 保持API返回的目录结构，但根目录使用配置的命名方式
            folder_path = file_info.get('folder_path', '')
            if folder_path:
                # 清理文件夹路径，移除不合法字符
                clean_folder_path = self.sanitize_folder_path(folder_path)
                if clean_folder_path:  # 确保清理后的路径不为空
                    # 创建子文件夹
                    subfolder_dir = os.path.join(self.download_dir, clean_folder_path)
                    subfolder_dir = os.path.normpath(subfolder_dir)  # 标准化路径
                    os.makedirs(subfolder_dir, exist_ok=True)
                    file_path = os.path.join(subfolder_dir, filename)
                    file_path = os.path.normpath(file_path)  # 标准化路径
                    print(f"下载文件到子文件夹: {clean_folder_path}/{filename}")
                else:
                    file_path = os.path.join(self.download_dir, filename)
                    file_path = os.path.normpath(file_path)  # 标准化路径
                    print(f"文件夹路径无效，下载文件到根目录: {filename}")
            else:
                file_path = os.path.join(self.download_dir, filename)
                file_path = os.path.normpath(file_path)  # 标准化路径
                print(f"下载文件到根目录: {filename}")

            # 检查文件是否已存在并完整
            if os.path.exists(file_path):
                file_downloaded = os.path.getsize(file_path)
                if file_downloaded >= file_size:
                    print(f"文件已完整下载，跳过: {filename}")
                    continue
            else:
                file_downloaded = 0

            # 记录下载前的总量，用于计算当前文件的贡献
            total_before_file = total_downloaded - file_downloaded if file_downloaded > 0 else total_downloaded
            
            # 尝试下载文件，如果速度过慢会重试
            download_success, new_file_downloaded = self.download_file_with_speed_monitor(
                download_url, file_path, file_downloaded, filename, 
                actual_total_size, total_before_file, proxy_url
            )
            
            if not download_success:
                return  # 下载失败，停止整个下载过程
            
            # 更新总下载量
            total_downloaded = total_before_file + new_file_downloaded

        if not self.is_cancelled:
            # 使用实际下载的总大小
            self.progress_updated.emit(100, actual_total_size, actual_total_size, "下载完成")
            self.download_finished.emit(self.work_id)

    def pause_download(self):
        self.is_paused = True

    def resume_download(self):
        self.is_paused = False

    def cancel_download(self):
        self.is_cancelled = True
        self.quit()

    def download_file_with_speed_monitor(self, download_url, file_path, initial_downloaded, filename, actual_total_size, total_downloaded_before, proxy_url):
        """下载单个文件，包含速度监控和重试逻辑"""
        max_retries = 3  # 最大重试次数
        retry_count = 0
        file_downloaded = initial_downloaded
        
        while retry_count <= max_retries:
            try:
                # 重置速度监控状态
                self.speed_check_start_time = time.time()
                self.last_speed_check_time = time.time()
                file_start_time = time.time()
                file_start_downloaded = file_downloaded
                
                headers = {}
                if file_downloaded > 0:
                    headers['Range'] = f'bytes={file_downloaded}-'
                    print(f"断点续传: {filename}, 从 {file_downloaded} 字节开始")

                print(f"开始下载文件: {filename} (尝试 {retry_count + 1}/{max_retries + 1})")
                response = requests.get(download_url, headers=headers, stream=True,
                                      proxies=proxy_url, timeout=self.request_timeout)
                response.raise_for_status()

                # 校验服务器是否真正支持断点续传：请求了 Range 却返回 200(而非 206)，
                # 说明服务器忽略 Range 发回了完整文件，此时若以追加模式写入会损坏文件，
                # 必须从头重新下载。
                resume = file_downloaded > 0 and response.status_code == 206
                if file_downloaded > 0 and response.status_code != 206:
                    print(f"服务器未按 Range 续传(状态码 {response.status_code})，从头重新下载: {filename}")
                    file_downloaded = 0
                    file_start_downloaded = 0
                # 进度计算的基准下载量：续传时为初始已下载量，否则从 0 计
                progress_base = initial_downloaded if resume else 0

                with open(file_path, 'ab' if resume else 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self.is_cancelled:
                            return False, file_downloaded

                        while self.is_paused and not self.is_cancelled:
                            time.sleep(0.1)

                        if chunk:
                            chunk_size = len(chunk)

                            # 使用令牌桶算法进行速度限制
                            self.consume_tokens(chunk_size)

                            f.write(chunk)
                            file_downloaded += chunk_size
                            current_total_downloaded = total_downloaded_before + (file_downloaded - progress_base)

                            # 更新进度
                            progress = min(int((current_total_downloaded / actual_total_size) * 100), 100) if actual_total_size > 0 else 0
                            self.progress_updated.emit(progress, current_total_downloaded, actual_total_size, "下载中...")

                            # 计算并发送速度更新
                            current_time = time.time()
                            time_diff = current_time - self.last_update_time

                            if time_diff >= 0.5:  # 每0.5秒更新一次速度
                                bytes_diff = current_total_downloaded - self.last_downloaded
                                speed_bps = bytes_diff / time_diff
                                speed_kbps = speed_bps / 1024

                                self.speed_updated.emit(self.work_id, speed_kbps)
                                self.last_update_time = current_time
                                self.last_downloaded = current_total_downloaded

                            # 检查下载速度（滑动窗口：只统计最近一个检查区间内的速度，
                            # 而非从文件开始至今的累计平均，否则前期高速会掩盖中途卡死）
                            file_elapsed = current_time - file_start_time
                            if file_elapsed >= self.min_speed_check_interval:
                                file_downloaded_in_period = file_downloaded - file_start_downloaded
                                file_speed_bps = file_downloaded_in_period / file_elapsed
                                file_speed_kbps = file_speed_bps / 1024

                                if file_speed_kbps < self.min_speed_kbps:
                                    print(f"文件 {filename} 速度过慢 ({file_speed_kbps:.2f} KB/s < {self.min_speed_kbps} KB/s)，重新下载")
                                    response.close()  # 关闭当前连接
                                    raise SpeedTooSlowException(f"速度过慢: {file_speed_kbps:.2f} KB/s")

                                # 重置窗口，下个区间重新测量
                                file_start_time = current_time
                                file_start_downloaded = file_downloaded

                # 文件下载完成
                print(f"文件下载完成: {filename}")
                return True, file_downloaded
                
            except SpeedTooSlowException as e:
                print(f"速度监控触发重试: {str(e)}")
                retry_count += 1
                if retry_count <= max_retries:
                    print(f"将在3秒后重试... ({retry_count}/{max_retries})")
                    time.sleep(3)  # 等待3秒后重试
                    continue
                else:
                    self.download_error.emit(self.work_id, f"文件 {filename} 下载失败: 多次重试后速度仍然过慢")
                    return False, file_downloaded
                    
            except requests.exceptions.RequestException as e:
                print(f"网络错误: {str(e)}")
                retry_count += 1
                if retry_count <= max_retries:
                    print(f"网络错误，将在5秒后重试... ({retry_count}/{max_retries})")
                    time.sleep(5)  # 网络错误等待更长时间
                    continue
                else:
                    self.download_error.emit(self.work_id, f"下载文件 {filename} 失败: {str(e)}")
                    return False, file_downloaded
                    
            except Exception as e:
                print(f"其他错误: {str(e)}")
                self.download_error.emit(self.work_id, f"保存文件 {filename} 失败: {str(e)}")
                return False, file_downloaded
        
        return False, file_downloaded

    def check_speed_and_retry_if_needed(self, current_time, total_downloaded):
        """检查下载速度，如果过慢则返回True表示需要重新下载"""
        if not self.speed_check_enabled:
            return False
            
        # 每隔指定时间检查一次速度
        if current_time - self.last_speed_check_time >= self.min_speed_check_interval:
            # 计算当前时间段内的平均速度
            time_elapsed = current_time - self.speed_check_start_time
            if time_elapsed > 0:
                bytes_downloaded_in_period = total_downloaded - (total_downloaded - (total_downloaded * (time_elapsed - self.min_speed_check_interval) / time_elapsed)) if time_elapsed > self.min_speed_check_interval else total_downloaded
                speed_bps = bytes_downloaded_in_period / time_elapsed
                speed_kbps = speed_bps / 1024
                self.current_speed_kbps = speed_kbps
                
                print(f"速度检查: 当前速度 {speed_kbps:.2f} KB/s, 最小要求 {self.min_speed_kbps} KB/s")
                
                # 如果速度低于最小要求，需要重新下载
                if speed_kbps < self.min_speed_kbps:
                    print(f"速度过慢 ({speed_kbps:.2f} KB/s < {self.min_speed_kbps} KB/s)，准备重新下载")
                    return True
                    
            # 重置检查时间
            self.last_speed_check_time = current_time
            self.speed_check_start_time = current_time
            
        return False

    def sanitize_filename(self, filename):
        """清理文件名，将Windows不支持的字符转换为相似字符"""
        filename = sanitize_windows_filename(filename)
        # 限制文件名长度
        if len(filename) > 200:
            name, ext = os.path.splitext(filename)
            filename = name[:200-len(ext)] + ext
        return filename

    def sanitize_folder_path(self, folder_path):
        """清理文件夹路径，保留路径分隔符但将不合法字符转换为相似字符"""
        return sanitize_folder_path(folder_path)


class MultiFileDownloadManager(QThread):
    """管理多个作品的下载"""
    download_started = pyqtSignal(str)  # work_id
    download_progress = pyqtSignal(str, int, 'PyQt_PyObject', 'PyQt_PyObject', str)  # work_id, progress%, downloaded, total, status
    download_completed = pyqtSignal(str)  # work_id
    download_failed = pyqtSignal(str, str)  # work_id, error
    speed_updated = pyqtSignal(str, float)  # work_id, speed
    file_filter_stats = pyqtSignal(str, 'PyQt_PyObject', 'PyQt_PyObject', 'PyQt_PyObject', int, int)  # work_id, api_total, actual_total, skipped_total, total_files, skipped_files

    def __init__(self, download_dir):
        super().__init__()
        self.download_dir = download_dir
        self.download_queue = []
        self.active_downloads = {}
        self.max_concurrent = 1  # 顺序下载，一次只下载一个

    def update_download_dir(self, new_download_dir):
        """动态更新下载目录"""
        self.download_dir = new_download_dir
        # 确保新目录存在
        if not os.path.exists(new_download_dir):
            os.makedirs(new_download_dir, exist_ok=True)
            print(f"创建新的下载目录: {new_download_dir}")

    def add_download(self, work_id, work_detail, work_info=None):
        """添加下载任务到队列"""
        self.download_queue.append((work_id, work_detail, work_info))

    def get_folder_name(self, work_id, work_detail, work_info=None):
        """根据配置获取文件夹名称，与旧方法保持一致"""
        conf = ReadConf()
        folder_for_name = conf.read_name()

        # 优先使用work_info（与旧方法一致），否则使用work_detail
        if work_info:
            work_title = sanitize_windows_filename(work_info['title'])
            rj_number = get_rj_number(work_info)  # 使用 source_id 或生成的 RJ 号
        else:
            work_title = sanitize_windows_filename(work_detail.get('title', f'Work_{work_id}'))
            # 如果没有 work_info，尝试从 work_detail 获取 source_id
            if 'source_id' in work_detail and work_detail['source_id']:
                rj_number = work_detail['source_id']
            else:
                # 最后才使用数字ID生成
                work_id_num = int(work_id)
                rj_number = f'RJ{work_id_num:06d}' if len(str(work_id_num)) == 6 else f'RJ{work_id_num:08d}'

        if folder_for_name == 'rj_naming':
            folder_name = rj_number
        elif folder_for_name == 'title_naming':
            folder_name = work_title
        elif folder_for_name == 'rj_space_title_naming':
            folder_name = f'{rj_number} {work_title}'
        elif folder_for_name == 'rj_underscore_title_naming':
            folder_name = f'{rj_number}_{work_title}'
        else:
            folder_name = work_title

        return folder_name

    def start_next_download(self):
        """开始下一个下载任务"""
        if len(self.active_downloads) >= self.max_concurrent or not self.download_queue:
            return

        # 处理新的参数格式
        queue_item = self.download_queue.pop(0)
        if len(queue_item) == 3:
            work_id, work_detail, work_info = queue_item
        else:
            work_id, work_detail = queue_item
            work_info = None

        # 根据配置的文件夹命名方式创建作品目录
        folder_name = self.get_folder_name(work_id, work_detail, work_info)
        print(f"生成的文件夹名: '{folder_name}'")
        work_dir = os.path.join(self.download_dir, folder_name)
        print(f"完整路径: '{work_dir}'")

        # 标准化路径并创建目录
        work_dir = os.path.normpath(work_dir)
        print(f"标准化后路径: '{work_dir}'")
        os.makedirs(work_dir, exist_ok=True)

        download_thread = DownloadThread(work_id, work_detail, work_dir)
        download_thread.progress_updated.connect(
            lambda p, d, t, s, wid=work_id: self.download_progress.emit(str(wid), p, d, t, s)
        )
        download_thread.download_finished.connect(self.on_download_finished)
        download_thread.download_error.connect(self.on_download_error)
        download_thread.speed_updated.connect(self.speed_updated.emit)
        download_thread.file_filter_stats.connect(
            lambda api, actual, skipped, total_f, skipped_f, wid=work_id: self.file_filter_stats.emit(str(wid), api, actual, skipped, total_f, skipped_f)
        )

        self.active_downloads[str(work_id)] = download_thread
        download_thread.start()
        self.download_started.emit(str(work_id))

    def on_download_finished(self, work_id):
        """下载完成处理"""
        if work_id in self.active_downloads:
            thread = self.active_downloads[work_id]
            thread.quit()
            thread.wait()
            del self.active_downloads[work_id]

        self.download_completed.emit(work_id)
        self.start_next_download()  # 开始下一个下载

    def on_download_error(self, work_id, error):
        """下载错误处理：跳过失败的作品并继续下载队列中的下一个

        (旧行为是清空整个队列并停止；一次临时网络抖动会把后面所有排队作品全部丢弃，
        改为只跳过当前失败作品，继续后续下载。)
        """
        if work_id in self.active_downloads:
            thread = self.active_downloads[work_id]
            thread.quit()
            thread.wait()
            del self.active_downloads[work_id]

        # 通知 UI 标记该作品失败（但不停止整体下载）
        self.download_failed.emit(work_id, error)

        # 继续下载队列中的下一个作品
        self.start_next_download()

    def pause_download(self, work_id):
        """暂停指定下载"""
        if work_id in self.active_downloads:
            self.active_downloads[work_id].pause_download()

    def resume_download(self, work_id):
        """继续指定下载"""
        if work_id in self.active_downloads:
            self.active_downloads[work_id].resume_download()

    def cancel_download(self, work_id):
        """取消指定下载"""
        if work_id in self.active_downloads:
            thread = self.active_downloads[work_id]
            thread.cancel_download()
            thread.wait()
            del self.active_downloads[work_id]

    def run(self):
        """下载管理器不需要独立工作线程。

        实际下载在各 DownloadThread 工作线程中进行；本管理器对象创建于主线程，
        其槽函数(on_download_finished / on_download_error / start_next_download)
        均通过信号在主线程的事件循环中执行，对 download_queue / active_downloads
        的访问全部发生在主线程，无需加锁。

        过去这里有一个 while 循环在管理器自己的工作线程里调用 start_next_download，
        会与主线程并发访问上述两个无锁字典(竞态)。现已不再以 start() 启动本线程，
        run() 保留为空以防误调用产生并发。
        """
        return