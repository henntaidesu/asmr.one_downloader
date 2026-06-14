"""
下载相关线程类模块
包含工作详情获取线程和下载列表获取线程
"""

from PyQt6.QtCore import QThread, pyqtSignal
from src.asmr_api.get_down_list import get_down_list
from src.download.download_utils import get_work_detail_sync, update_work_review_status


class ReviewThread(QThread):
    """后台更新作品收听状态(review)的线程

    review() 会发同步 HTTP 请求；放在后台线程执行，避免在主线程(下载完成回调)
    中阻塞 UI。
    """
    review_done = pyqtSignal(str, bool)  # work_id, success

    def __init__(self, work_id, progress=None):
        super().__init__()
        self.work_id = work_id
        self.progress = progress  # 指定状态(如 'postponed' 搁置)，None 表示按默认(听过/在听)

    def run(self):
        try:
            ok = update_work_review_status(self.work_id, progress=self.progress)
            self.review_done.emit(str(self.work_id), bool(ok))
        except Exception as e:
            print(f"review 线程错误: {e}")
            self.review_done.emit(str(self.work_id), False)


class WorkDetailThread(QThread):
    """工作详情获取线程"""
    detail_loaded = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, work_id):
        super().__init__()
        self.work_id = work_id

    def run(self):
        try:
            detail = get_work_detail_sync(self.work_id)
            # 错误哨兵(如 TOKEN_EXPIRED)以字符串形式返回，需作为错误传播而非详情
            if isinstance(detail, str):
                self.error_occurred.emit(detail)
            elif detail:
                self.detail_loaded.emit(detail)
            else:
                self.error_occurred.emit("Failed to get work detail")
        except Exception as e:
            self.error_occurred.emit(str(e))


class DownloadListThread(QThread):
    """下载列表获取线程"""
    list_updated = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()

    def run(self):
        try:
            print("开始获取下载列表...")
            works_list = get_down_list()
            
            # 检查是否返回了错误标识
            if isinstance(works_list, str):
                if works_list == "TOKEN_EXPIRED":
                    self.error_occurred.emit("TOKEN_EXPIRED")
                    return
                elif works_list == "NETWORK_ERROR":
                    self.error_occurred.emit("NETWORK_ERROR")
                    return
                elif works_list == "API_ERROR":
                    self.error_occurred.emit("API_ERROR")
                    return
                elif works_list == "JSON_PARSE_ERROR":
                    self.error_occurred.emit("JSON_PARSE_ERROR")
                    return
            
            # 检查是否是有效的列表数据
            if isinstance(works_list, list):
                if works_list:
                    print(f"成功获取到 {len(works_list)} 个下载项目")
                else:
                    print("API返回的works列表为空，但这是有效的响应")
                self.list_updated.emit(works_list)
            else:
                error_msg = "API返回数据格式错误"
                print(f"错误: {error_msg}")
                self.error_occurred.emit("EMPTY_LIST")
        except Exception as e:
            error_msg = f"Failed to get download list: {str(e)}"
            print(f"异常错误: {error_msg}")
            print(f"异常类型: {type(e).__name__}")
            import traceback
            print(f"完整错误堆栈:")
            traceback.print_exc()
            self.error_occurred.emit(f"EXCEPTION: {str(e)}")
