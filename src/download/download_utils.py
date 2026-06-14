"""
下载页面工具函数模块
包含文件大小计算、格式化等实用功能函数
"""

import os
import re
import time
from src.read_conf import ReadConf
from src.download.re_title import sanitize_windows_filename


def format_bytes(bytes_value):
    """格式化字节数为可读格式，支持超大文件(>100GB)"""
    # 确保 bytes_value 是数字类型
    if isinstance(bytes_value, str):
        try:
            bytes_value = float(bytes_value)
        except ValueError:
            return "0 B"
    
    if bytes_value == 0:
        return "0 B"
    elif bytes_value >= 1024 * 1024 * 1024 * 1024:  # TB
        return f"{bytes_value / (1024 * 1024 * 1024 * 1024):.2f} TB"
    elif bytes_value >= 1024 * 1024 * 1024:  # GB
        return f"{bytes_value / (1024 * 1024 * 1024):.2f} GB"
    elif bytes_value >= 1024 * 1024:  # MB
        return f"{bytes_value / (1024 * 1024):.2f} MB"
    elif bytes_value >= 1024:  # KB
        return f"{bytes_value / 1024:.1f} KB"
    else:
        return f"{int(bytes_value)} B"


def calculate_actual_total_size(work_detail):
    """计算实际需要下载的文件总大小（排除跳过的文件）"""
    if not work_detail:
        return 0

    conf = ReadConf()
    selected_formats = conf.read_downfile_type()

    actual_total_size = 0
    for file_info in work_detail['files']:
        file_title = file_info['title']
        file_type = file_title[file_title.rfind('.') + 1:].upper()
        if not selected_formats.get(file_type, False):
            continue  # 跳过不需要的文件类型

        file_size = file_info.get('size', 0)
        if isinstance(file_size, str):
            try:
                file_size = int(file_size)
            except ValueError:
                file_size = 0
        actual_total_size += file_size

    return actual_total_size


def calculate_downloaded_size(work_detail, work_info):
    """计算已下载的文件大小"""
    if not work_detail:
        return 0

    downloaded_size = 0
    conf = ReadConf()
    download_conf = conf.read_download_conf()

    # 读取文件类型配置
    selected_formats = conf.read_downfile_type()
    download_dir = download_conf['download_path']
    
    # 根据文件夹命名方式获取实际文件夹路径
    folder_for_name = conf.read_name()
    work_title = sanitize_windows_filename(work_info['title'])
    rj_number = get_rj_number(work_info)  # 使用 source_id 或生成的 RJ 号
    
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
        
    work_download_dir = os.path.join(download_dir, folder_name)
    
    try:
        if os.path.exists(work_download_dir):
            for file_info in work_detail['files']:
                file_title = sanitize_windows_filename(file_info['title'])

                # 按照旧方法的逻辑进行文件类型筛选
                file_type = file_title[file_title.rfind('.') + 1:].upper()
                if not selected_formats.get(file_type, False):
                    continue  # 跳过不需要的文件类型
                
                # 获取文件夹路径并创建完整的文件路径
                folder_path = file_info.get('folder_path', '')
                if folder_path:
                    # 清理文件夹路径
                    clean_folder_path = re.sub(r'[<>:"|?*]', '_', folder_path)
                    clean_folder_path = clean_folder_path.rstrip('. ')
                    # 替换路径分隔符为本地格式
                    clean_folder_path = clean_folder_path.replace('/', os.sep)
                    
                    file_path = os.path.join(work_download_dir, clean_folder_path, file_title)
                else:
                    file_path = os.path.join(work_download_dir, file_title)
                
                if os.path.exists(file_path):
                    # 使用os.path.getsize获取实际文件大小，支持大文件
                    actual_size = os.path.getsize(file_path)
                    expected_size = file_info.get('size', 0)
                    # 确保expected_size是数字类型，支持超大数值
                    if isinstance(expected_size, str):
                        try:
                            expected_size = int(expected_size)
                        except ValueError:
                            expected_size = 0
                    
                    # 取实际大小和期望大小的最小值，避免超过文件实际大小
                    downloaded_size += min(actual_size, expected_size)
    except Exception as e:
        print(f"计算已下载大小时出错: {e}")
        return 0
    
    return downloaded_size


def build_file_tree_structure(work_detail):
    """构建文件目录树结构"""
    if not work_detail or 'files' not in work_detail:
        return {}

    # 获取文件类型配置
    conf = ReadConf()
    selected_formats = conf.read_downfile_type()

    # 构建目录结构
    file_tree = {}
    for file_info in work_detail['files']:
        file_title = file_info['title']
        folder_path = file_info.get('folder_path', '')

        # 判断文件是否会被跳过
        file_type = file_title[file_title.rfind('.') + 1:].upper()
        is_skipped = not selected_formats.get(file_type, False)

        # 处理文件夹路径
        if folder_path:
            # 分割路径，创建嵌套结构
            path_parts = folder_path.strip('/').split('/')
            current_tree = file_tree

            # 创建文件夹结构
            for part in path_parts:
                if part not in current_tree:
                    current_tree[part] = {'type': 'folder', 'children': {}}
                current_tree = current_tree[part]['children']

            # 添加文件到相应文件夹
            current_tree[file_title] = {
                'type': 'file',
                'size': file_info.get('size', 0),
                'skipped': is_skipped
            }
        else:
            # 根目录文件
            file_tree[file_title] = {
                'type': 'file',
                'size': file_info.get('size', 0),
                'skipped': is_skipped
            }

    return file_tree


def check_all_files_skipped(children_dict):
    """递归检查文件夹内所有文件是否都被跳过"""
    for name, item in children_dict.items():
        if item['type'] == 'file':
            if not item.get('skipped', False):
                return False  # 发现有文件不被跳过
        elif item['type'] == 'folder':
            if not check_all_files_skipped(item['children']):
                return False  # 子文件夹内有文件不被跳过
    return True  # 所有文件都被跳过


def set_initial_collapsed_folders(tree_dict, folder_path, collapsed_folders):
    """初始化时将所有跳过的文件夹设为折叠状态"""
    for name, item in tree_dict.items():
        if item['type'] == 'folder':
            current_path = f"{folder_path}/{name}" if folder_path else name
            if check_all_files_skipped(item['children']):
                collapsed_folders.add(current_path)
            # 递归处理子文件夹
            set_initial_collapsed_folders(item['children'], current_path, collapsed_folders)


def get_work_folder_name(work_info):
    """根据配置获取作品文件夹名称"""
    conf = ReadConf()
    folder_for_name = conf.read_name()
    work_title = sanitize_windows_filename(work_info['title'])
    rj_number = get_rj_number(work_info)  # 使用 source_id 或生成的 RJ 号
    
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


def format_file_size_for_filter_stats(size):
    """格式化文件大小用于筛选统计信息显示"""
    if size >= 1024**3:
        return f"{size / (1024**3):.2f} GB"
    elif size >= 1024**2:
        return f"{size / (1024**2):.2f} MB"
    elif size >= 1024:
        return f"{size / 1024:.2f} KB"
    else:
        return f"{size} B"


def format_rj_number(work_id):
    """格式化RJ号显示（已废弃，保留用于向后兼容）"""
    return f"RJ{work_id:06d}" if len(str(work_id)) == 6 else f"RJ{work_id:08d}"


def get_rj_number(work_info):
    """
    从 work_info 中获取 RJ 号
    优先使用 source_id 字段，如果没有则使用 id 生成
    
    Args:
        work_info: 作品信息字典，应包含 'source_id' 或 'id' 字段
    
    Returns:
        str: RJ 号字符串，如 "RJ01128508"
    """
    # 优先使用 source_id
    if 'source_id' in work_info and work_info['source_id']:
        return work_info['source_id']
    
    # 如果没有 source_id，使用 id 生成（向后兼容）
    work_id = work_info.get('id', 0)
    return f"RJ{work_id:06d}" if len(str(work_id)) == 6 else f"RJ{work_id:08d}"


def get_work_detail_sync(work_id):
    """同步获取作品详细信息"""
    try:
        from src.asmr_api.get_work_detail import get_work_detail
        return get_work_detail(work_id)
    except Exception as e:
        print(f"获取作品详情失败: {e}")
        return None


def update_work_review_status(work_id, progress=None):
    """更新作品收听状态。progress 指定时直接使用(如 'postponed' 搁置)，否则按 DB 配置取听过/在听"""
    try:
        from src.asmr_api.works_review import review
        conf = ReadConf()
        check_db = conf.check_DB()
        review(int(work_id), check_db, progress=progress)
        print(f"已更新作品 RJ{work_id} 的状态: {progress or ('listened' if check_db else 'listening')}")
        return True
    except Exception as e:
        print(f"更新作品状态失败: {str(e)}")
        return False


def calculate_initial_progress(work_detail, work_info):
    """计算初始下载进度"""
    if not work_detail:
        return 0, 0, 0
    
    actual_total_size = calculate_actual_total_size(work_detail)
    downloaded_size = calculate_downloaded_size(work_detail, work_info)
    
    # 计算初始进度
    initial_progress = int((downloaded_size / actual_total_size) * 100) if actual_total_size > 0 else 0
    
    return initial_progress, downloaded_size, actual_total_size


def format_speed_display(speed_kbps):
    """格式化速度显示"""
    if speed_kbps >= 1024:
        return f"{speed_kbps/1024:.2f} MB/s"
    else:
        return f"{speed_kbps:.1f} KB/s"


def build_file_filter_stats_text(work_id, total_files, skipped_files, skipped_total, actual_total):
    """构建文件筛选统计信息文本
    
    注意：work_id 参数可以是数字ID或RJ号字符串
    """
    # 如果 work_id 是数字，格式化为 RJ 号；如果已经是字符串（RJ号），直接使用
    if isinstance(work_id, (int, float)):
        rj_display = f"RJ{int(work_id):08d}"
    else:
        rj_display = work_id
    
    status_text = f"作品 {rj_display}: "
    status_text += f"总文件 {total_files} 个, "
    if skipped_files > 0:
        status_text += f"跳过 {skipped_files} 个({format_file_size_for_filter_stats(skipped_total)}), "
    status_text += f"下载 {total_files - skipped_files} 个({format_file_size_for_filter_stats(actual_total)})"
    return status_text


def validate_work_detail_for_download(work_detail):
    """验证作品详情是否可用于下载"""
    if not work_detail:
        return False
    return 'files' in work_detail and len(work_detail['files']) > 0


def create_download_item_data(work_id, work_detail):
    """创建下载项数据"""
    if not validate_work_detail_for_download(work_detail):
        return None
    return str(work_id), work_detail


def calculate_global_speed(download_items):
    """计算全局下载速度"""
    total_speed = 0.0
    for item in download_items.values():
        if hasattr(item, 'is_downloading') and hasattr(item, 'is_paused') and hasattr(item, 'download_speed'):
            if item.is_downloading and not item.is_paused:
                total_speed += item.download_speed
    return total_speed
