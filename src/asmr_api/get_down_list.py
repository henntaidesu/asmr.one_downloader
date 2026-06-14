import requests
from src.read_conf import ReadConf


def get_down_list():
    conf = ReadConf()
    check_DB = conf.check_DB()

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

    if check_DB:
        url = f'https://api.{web_site}/api/review?order=updated_at&sort=desc&page=1&filter=listening'
    else:
        url = f'https://api.{web_site}/api/review?order=updated_at&sort=desc&page=1&filter=marked'

    user_data = conf.read_asmr_user()
    token = user_data['token']
    headers = {
        'authorization': f'Bearer {token}'
    }

    proxy = conf.read_proxy_conf()
    if proxy['open_proxy']:
        proxy_url = {
            f'http': f'{proxy["proxy_type"]}://{proxy["host"]}:{proxy["port"]}',
            f'https': f'{proxy["proxy_type"]}://{proxy["host"]}:{proxy["port"]}'
        }
    else:
        proxy_url = None

    try:
        # 发送API请求
        response = requests.get(url, headers=headers, proxies=proxy_url)
        
        # 打印调试信息
        # print(f"API请求URL: {url}")
        # print(f"响应状态码: {response.status_code}")
        # print(f"响应头信息: {response.headers}")
        # print(f"API原始响应: {response.text}")
        
        # 检查响应状态码
        if response.status_code == 401:
            print(f"Token认证失败，状态码: 401")
            print(f"响应内容: {response.text}")
            # 返回特殊标识，用于UI层识别
            return "TOKEN_EXPIRED"
        elif response.status_code != 200:
            print(f"API请求失败，状态码: {response.status_code}")
            print(f"响应内容: {response.text}")
            return "API_ERROR"
        
        # 尝试解析JSON
        req = response.json()
        # print(f"解析后的JSON数据: {req}")
        
    except requests.exceptions.RequestException as e:
        print(f"网络请求异常: {e}")
        return "NETWORK_ERROR"
    except ValueError as e:
        print(f"JSON解析失败: {e}")
        print(f"响应文本: {response.text}")
        return "JSON_PARSE_ERROR"
    
    id_list = []

    # 检查返回数据结构
    if 'works' in req:
        if req['works']:
            print(f"成功获取到 {len(req['works'])} 个作品")
            data = req['works']
            for work in data:
                work_id = work['id']
                # source_id 是站点规范 RJ 号；缺失时按号长度回退(6 位号补 6 位，否则 8 位)，
                # 避免对经典 6 位作品错误补成 8 位导致目录命名不符
                rj_fallback = f"RJ{work_id:06d}" if len(str(work_id)) == 6 else f"RJ{work_id:08d}"
                work_info = {
                    'id': work_id,
                    'title': work['title'],
                    'source_id': work.get('source_id') or rj_fallback,
                }
                id_list.append(work_info)
        else:
            print("API返回的works列表为空")
    else:
        print("API返回数据中没有'works'字段")
        print(f"可用字段: {list(req.keys())}")

    return id_list