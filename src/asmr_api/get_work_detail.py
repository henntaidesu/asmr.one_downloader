import requests
from src.read_conf import ReadConf


def get_work_detail(work_id):
    """
    获取作品详细信息，包括文件列表和下载链接

    Args:
        work_id (int): 作品ID

    Returns:
        dict: 包含作品详细信息的字典，如果失败返回None
    """
    conf = ReadConf()

    website_course = conf.read_website_course()
    if website_course == 'Original':
        web_site = 'asmr.one'
    elif website_course == 'Mirror-1':
        web_site = 'asmr-100.com'
    elif website_course == 'Mirror-2':
        web_site = 'asmr-200.com'
    elif website_course == 'Mirror-3':
        web_site = 'asmr-300.com'
    else:
        # 配置值非法时回退到原站，避免 web_site 未定义抛 NameError
        web_site = 'asmr.one'

    url = f'https://api.{web_site}/api/tracks/{work_id}?v=1'

    user_data = conf.read_asmr_user()
    token = user_data['token']
    headers = {
        'authorization': f'Bearer {token}'
    }

    proxy = conf.read_proxy_conf()
    if proxy['open_proxy']:
        proxy_url = {
            'http': f'{proxy["proxy_type"]}://{proxy["host"]}:{proxy["port"]}',
            'https': f'{proxy["proxy_type"]}://{proxy["host"]}:{proxy["port"]}'
        }
    else:
        proxy_url = None

    try:
        response = requests.get(url, headers=headers, proxies=proxy_url)
        # 区分 token 过期：与 get_down_list 保持一致返回 TOKEN_EXPIRED 哨兵，
        # 而非笼统当作网络错误返回 None，使 UI 能提示重新登录
        if response.status_code == 401:
            print("获取作品详情失败：Token 认证失败 (401)")
            return "TOKEN_EXPIRED"
        response.raise_for_status()
        tracks_data = response.json()

        # API返回的是数组格式
        if not tracks_data or not isinstance(tracks_data, list):
            return None

        # 从第一个track获取作品基本信息
        first_track = tracks_data[0] if tracks_data else {}
        work_info = first_track.get('work', {})

        work_detail = {
            'id': work_info.get('id', work_id),
            'title': first_track.get('workTitle', ''),
            'circle': '',  # API中没有circle信息
            'dl_count': 0,  # API中没有dl_count信息
            'total_size': 0,
            'files': []
        }

        # 递归处理文件夹结构
        def process_items(items, prefix_path=""):
            for item in items:
                if item.get('type') == 'folder' and 'children' in item:
                    # 递归处理文件夹
                    folder_path = f"{prefix_path}/{item.get('title', '')}" if prefix_path else item.get('title', '')
                    process_items(item['children'], folder_path)
                elif item.get('mediaDownloadUrl'):
                    # 处理文件 - 尝试多种字段获取文件大小
                    file_size = (
                        item.get('size', 0) or 
                        item.get('fileSize', 0) or 
                        item.get('streamSize', 0) or 
                        item.get('contentLength', 0)
                    )
                    
                    print(f"文件: {item.get('title', '未知')} - API返回大小: {file_size}")

                    # 如果API没有提供文件大小，尝试通过HEAD请求获取
                    if file_size == 0:
                        try:
                            print(f"尝试通过HEAD请求获取文件大小: {item.get('title', '未知')}")
                            head_response = requests.head(item.get('mediaDownloadUrl'),
                                                        headers=headers, proxies=proxy_url, timeout=15)
                            content_length = head_response.headers.get('content-length')
                            if content_length:
                                file_size = int(content_length)
                                print(f"HEAD请求获得文件大小: {file_size} bytes")
                            else:
                                print(f"HEAD请求未返回Content-Length头部")
                        except Exception as e:
                            print(f"HEAD请求失败: {str(e)}")
                            file_size = 0  # 如果获取失败，保持为0

                    file_info = {
                        'title': item.get('title', ''),
                        'download_url': item.get('mediaDownloadUrl'),
                        'size': file_size,
                        'duration': item.get('duration', 0) if item.get('type') == 'audio' else 0,
                        'hash': item.get('hash', ''),
                        'type': item.get('type', 'other'),
                        'folder_path': prefix_path
                    }
                    work_detail['files'].append(file_info)
                    work_detail['total_size'] += file_info['size']

        # 处理所有文件和文件夹
        process_items(tracks_data)
        
        # 打印调试信息
        print(f"作品 {work_detail['id']} 文件统计:")
        print(f"  总文件数: {len(work_detail['files'])}")
        print(f"  总大小: {work_detail['total_size']} bytes ({work_detail['total_size'] / (1024*1024):.2f} MB)")
        
        # 统计大小为0的文件数量
        zero_size_files = [f for f in work_detail['files'] if f['size'] == 0]
        if zero_size_files:
            print(f"  警告: {len(zero_size_files)} 个文件大小为0:")
            for f in zero_size_files[:5]:  # 只显示前5个
                print(f"    - {f['title']}")
            if len(zero_size_files) > 5:
                print(f"    ... 还有 {len(zero_size_files)-5} 个文件")

        return work_detail

    except requests.exceptions.RequestException as e:
        print(f"网络请求失败：{str(e)}")
        return None
    except Exception as e:
        print(f"获取作品详细信息时发生错误：{str(e)}")
        return None