import requests
import os
import sys

# 添加项目根目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from src.read_conf import ReadConf


def review(work_id, check_DB, progress=None):
    """
    更新作品的收听状态

    Args:
        work_id (int): 作品ID
        check_DB (bool): 是否标记为已听完（True）或正在收听（False）
        progress (str): 直接指定状态值(如 'postponed' 搁置)，给定时优先于 check_DB

    Returns:
        bool: 是否更新成功
    """
    try:
        # asmr.one 状态枚举：marked(想听)/listening(在听)/listened(听过)/replay(重听)/postponed(搁置)
        if progress is None:
            progress = 'listened' if check_DB else 'listening'
        print(f"更新作品 {work_id} 状态: {progress}")

        conf = ReadConf()

        website_course = conf.read_website_course()
        if website_course == 'Original':
            web_site = f'asmr.one'
        elif website_course == 'Mirror-1':
            web_site = 'asmr-100.com'
        elif website_course == 'Mirror-2':
            web_site = 'asmr-200.com'
        elif website_course == 'Mirror-3':
            web_site = 'asmr-300.com'
        else:
            # 配置值非法时回退到原站，避免 web_site 未定义抛 NameError
            web_site = 'asmr.one'
        url = f'https://api.{web_site}/api/review'

        user_data = conf.read_asmr_user()
        token = user_data['token']
        headers = {
            'authorization': f'Bearer {token}'
        }
        data = {
            'progress': progress,
            'work_id': work_id,
        }

        proxy = conf.read_proxy_conf()
        if proxy['open_proxy']:
            proxy_url = {
                f'http': f'{proxy["proxy_type"]}://{proxy["host"]}:{proxy["port"]}',
                f'https': f'{proxy["proxy_type"]}://{proxy["host"]}:{proxy["port"]}'
            }
        else:
            proxy_url = None

        # asmr.one 的 /api/review 接口期望 JSON body，用 json= 而非 data=(form 编码)
        response = requests.put(url, headers=headers, json=data, proxies=proxy_url, timeout=30)
        response.raise_for_status()
        print(f"成功更新作品 {work_id} 状态")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"网络请求失败: {str(e)}")
        return False
    except Exception as e:
        print(f"更新作品状态时发生错误: {str(e)}")
        return False
