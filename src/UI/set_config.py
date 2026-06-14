import re
from xmlrpc.client import ServerProxy

from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QMainWindow,
    QPushButton,
    QLineEdit,
    QMessageBox,
    QComboBox,
    QLabel,
    QCheckBox,
    QFileDialog,
)
from PyQt6 import QtCore, QtWidgets
from src.read_conf import ReadConf
from src.language.language_manager import language_manager
import ipaddress


class LoginThread(QThread):
    """异步登录线程，避免阻塞主界面"""
    login_finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, username, password):
        super().__init__()
        self.username = username
        self.password = password
    
    def run(self):
        try:
            # 先保存用户名和密码到配置文件
            from src.read_conf import ReadConf
            conf = ReadConf()
            conf.write_asmr_username(self.username, self.password)
            
            # 执行登录
            from src.asmr_api.login import login
            result = login()
            print(f"{language_manager.get_text('login_result')}: {result}")  # 调试信息

            if result is True:
                self.login_finished.emit(True, language_manager.get_text('login_successful'))
            else:
                self.login_finished.emit(False, str(result))
                
        except Exception as e:
            self.login_finished.emit(False, f"{language_manager.get_text('login_error')}：{str(e)}")


class SetConfig(QMainWindow):
    # 添加信号，当下载路径更改时发出
    download_path_changed = pyqtSignal()
    # 添加信号，用于接收语言切换通知
    language_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # 配置读取
        self.conf = ReadConf()
        self.selected_formats = self.conf.read_downfile_type()
        self.proxy_conf = self.conf.read_proxy_conf()


        # 创建界面组件
        self.setWindowTitle(language_manager.get_text('app_title'))
        self.setFixedSize(450, 450)  # 增加窗口尺寸以适应优化后的布局和多语言文本

        self.centralwidget = QtWidgets.QWidget(self)
        self.setCentralWidget(self.centralwidget)

        # 下载路径设置区域
        self.download_path_label = QLabel(language_manager.get_text('download_path_settings'), self.centralwidget)
        self.download_path_label.setGeometry(QtCore.QRect(10, 10, 300, 20))
        self.download_path_label.setStyleSheet('font-weight: bold; color: #2c3e50;')

        # 创建并配置 QLineEdit - 第一行：下载路径
        self.down_path = QLineEdit(self.centralwidget)
        self.down_path.setGeometry(QtCore.QRect(10, 35, 340, 30))
        self.down_path.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.down_path.setPlaceholderText(language_manager.get_text('download_path'))

        # 网络设置区域
        self.network_settings_label = QLabel(language_manager.get_text('network_settings'), self.centralwidget)
        self.network_settings_label.setGeometry(QtCore.QRect(10, 70, 100, 20))
        self.network_settings_label.setStyleSheet('font-weight: bold; color: #2c3e50;')

        # 第一行：下载限速设置（左侧）
        self.speed_limit_desc_label = QLabel(language_manager.get_text('download_speed_limit'), self.centralwidget)
        self.speed_limit_desc_label.setGeometry(QtCore.QRect(10, 90, 140, 30))
        self.speed_limit_desc_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.speed_limit = QLineEdit(self.centralwidget)
        self.speed_limit.setGeometry(QtCore.QRect(155, 90, 40, 30))
        self.speed_limit.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.speed_limit.setPlaceholderText(language_manager.get_text('speed'))
        self.speed_limit.editingFinished.connect(self.save_speed_limit)

        self.speed_limit_label = QLabel(language_manager.get_text('mb_per_s'), self.centralwidget)
        self.speed_limit_label.setGeometry(QtCore.QRect(200, 90, 50, 30))
        self.speed_limit_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        # 第一行：下载源设置（右侧）
        self.download_source_label = QLabel(language_manager.get_text('download_source'), self.centralwidget)
        self.download_source_label.setGeometry(QtCore.QRect(260, 90, 110, 30))
        self.download_source_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.file_download_source = QComboBox(self.centralwidget)
        self.file_download_source.setGeometry(QtCore.QRect(365, 90, 80, 30))
        self.file_download_source.addItem("Original")
        self.file_download_source.addItem("Mirror-1")
        self.file_download_source.addItem("Mirror-2")
        self.file_download_source.addItem("Mirror-3")
        self.file_download_source.currentTextChanged.connect(self.set_file_download_source)

        # 第二行：代理设置（分为两个逻辑组件）
        # 左侧：代理开关和类型
        self.open_proxy = QCheckBox(language_manager.get_text('use_proxy'), self.centralwidget)
        self.open_proxy.setGeometry(QtCore.QRect(10, 125, 120, 30))
        self.open_proxy.setChecked(self.proxy_conf["open_proxy"])
        self.open_proxy.toggled.connect(self.save_open_proxy)

        self.set_proxy_type = QComboBox(self.centralwidget)
        self.set_proxy_type.setGeometry(QtCore.QRect(135, 125, 65, 30))
        self.set_proxy_type.addItem("http")
        self.set_proxy_type.addItem("https")
        self.set_proxy_type.addItem("socks5")
        self.set_proxy_type.addItem("socks4")
        self.set_proxy_type.currentTextChanged.connect(self.save_proxy_type)

        # 右侧：代理地址和端口
        self.proxy_address = QLineEdit(self.centralwidget)
        self.proxy_address.setGeometry(QtCore.QRect(220, 125, 135, 30))
        self.proxy_address.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.proxy_address.setPlaceholderText(language_manager.get_text('proxy_address'))
        self.proxy_address.editingFinished.connect(self.save_proxy_address)

        self.proxy_port = QLineEdit(self.centralwidget)
        self.proxy_port.setGeometry(QtCore.QRect(365, 125, 80, 30))
        self.proxy_port.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.proxy_port.setPlaceholderText(language_manager.get_text('port'))
        self.proxy_port.editingFinished.connect(self.save_proxy_port)

        # 用户登录区域
        self.login_label = QLabel(language_manager.get_text('user_login'), self.centralwidget)
        self.login_label.setGeometry(QtCore.QRect(10, 165, 100, 20))
        self.login_label.setStyleSheet('font-weight: bold; color: #2c3e50;')

        # 用户名和密码（每行两个组件的布局）
        self.user_name = QLineEdit(self.centralwidget)
        self.user_name.setGeometry(QtCore.QRect(10, 185, 160, 30))
        self.user_name.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.user_name.setPlaceholderText(language_manager.get_text('user_name'))

        self.password = QLineEdit(self.centralwidget)
        self.password.setGeometry(QtCore.QRect(180, 185, 160, 30))
        self.password.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.password.setPlaceholderText(language_manager.get_text('password'))

        # 设置下载路径按钮
        self.path_conf_save_button = QPushButton(language_manager.get_text('select'), self.centralwidget)
        self.path_conf_save_button.setGeometry(QtCore.QRect(365, 35, 80, 30))
        self.path_conf_save_button.clicked.connect(self.save_download_path)

        # 登录按钮
        self.user_conf_save_button = QPushButton(language_manager.get_text('login'), self.centralwidget)
        self.user_conf_save_button.setGeometry(QtCore.QRect(350, 185, 95, 30))
        self.user_conf_save_button.clicked.connect(self.save_user)

        # 下载设置区域
        self.download_settings_label = QLabel(language_manager.get_text('download_settings'), self.centralwidget)
        self.download_settings_label.setGeometry(QtCore.QRect(10, 220, 100, 20))
        self.download_settings_label.setStyleSheet('font-weight: bold; color: #2c3e50;')

        # 第一行：最大重试次数（左侧组件）
        self.max_retries_desc_label = QLabel(language_manager.get_text('retry_count'), self.centralwidget)
        self.max_retries_desc_label.setGeometry(QtCore.QRect(10, 240, 100, 30))
        self.max_retries_desc_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.max_retries = QLineEdit(self.centralwidget)
        self.max_retries.setGeometry(QtCore.QRect(115, 240, 60, 30))
        self.max_retries.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.max_retries.setPlaceholderText(language_manager.get_text('max_retries'))
        self.max_retries.editingFinished.connect(self.save_max_retries)
        
        self.max_retries_label = QLabel(language_manager.get_text('times'), self.centralwidget)
        self.max_retries_label.setGeometry(QtCore.QRect(180, 240, 35, 30))
        self.max_retries_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        # 第一行：下载超时时间（右侧组件）
        self.timeout_desc_label = QLabel(language_manager.get_text('timeout_time'), self.centralwidget)
        self.timeout_desc_label.setGeometry(QtCore.QRect(250, 240, 90, 30))
        self.timeout_desc_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.timeout = QLineEdit(self.centralwidget)
        self.timeout.setGeometry(QtCore.QRect(345, 240, 60, 30))
        self.timeout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.timeout.setPlaceholderText(language_manager.get_text('timeout'))
        self.timeout.editingFinished.connect(self.save_timeout)
        
        self.time_out_label = QLabel(language_manager.get_text('seconds'), self.centralwidget)
        self.time_out_label.setGeometry(QtCore.QRect(410, 240, 35, 30))
        self.time_out_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        # 第二行：最小速度设置（左侧组件）
        self.min_speed_desc_label = QLabel(language_manager.get_text('min_speed'), self.centralwidget)
        self.min_speed_desc_label.setGeometry(QtCore.QRect(10, 270, 100, 30))
        self.min_speed_desc_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        
        self.min_speed = QLineEdit(self.centralwidget)
        self.min_speed.setGeometry(QtCore.QRect(115, 270, 60, 30))
        self.min_speed.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.min_speed.setPlaceholderText('256')
        self.min_speed.editingFinished.connect(self.save_min_speed)
        
        self.min_speed_label = QLabel(language_manager.get_text('kb_per_s'), self.centralwidget)
        self.min_speed_label.setGeometry(QtCore.QRect(180, 270, 35, 30))
        self.min_speed_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        
        # 第二行：检查间隔设置（右侧组件）
        self.min_speed_check_desc_label = QLabel(language_manager.get_text('check_interval'), self.centralwidget)
        self.min_speed_check_desc_label.setGeometry(QtCore.QRect(250, 270, 90, 30))
        self.min_speed_check_desc_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        
        self.min_speed_check = QLineEdit(self.centralwidget)
        self.min_speed_check.setGeometry(QtCore.QRect(345, 270, 60, 30))
        self.min_speed_check.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.min_speed_check.setPlaceholderText('30')
        self.min_speed_check.editingFinished.connect(self.save_min_speed_check)
        
        self.min_speed_check_label = QLabel(language_manager.get_text('second'), self.centralwidget)
        self.min_speed_check_label.setGeometry(QtCore.QRect(410, 270, 30, 30))
        self.min_speed_check_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        # 第三行：文件夹命名方式（居左布局）
        self.label = QLabel(language_manager.get_text('folder_naming'), self.centralwidget)
        self.label.setGeometry(QtCore.QRect(10, 300, 120, 30))
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        # 创建下拉选择框
        self.folder_name_type_combo_box = QComboBox(self.centralwidget)
        self.folder_name_type_combo_box.setGeometry(QtCore.QRect(115, 300, 180, 30))
        self.folder_name_type_combo_box.addItem(language_manager.get_text('rj_naming'))
        self.folder_name_type_combo_box.addItem(language_manager.get_text('title_naming'))
        self.folder_name_type_combo_box.addItem(language_manager.get_text('rj_space_title_naming'))
        self.folder_name_type_combo_box.addItem(language_manager.get_text('rj_underscore_title_naming'))
        self.folder_name_type_combo_box.currentTextChanged.connect(self.set_folder_for_name)



        # 文件类型选择区域
        self.file_types_label = QLabel(language_manager.get_text('file_type_selection'), self.centralwidget)
        self.file_types_label.setGeometry(QtCore.QRect(10, 340, 120, 20))
        self.file_types_label.setStyleSheet('font-weight: bold; color: #2c3e50;')

        # 文件类型选择：每行5个复选框，两行布局
        # 第一行：音频和视频格式
        self.checkbox_MP3 = QCheckBox("MP3", self.centralwidget)
        self.checkbox_MP3.setGeometry(QtCore.QRect(10, 365, 60, 30))
        self.checkbox_MP3.setChecked(self.selected_formats["MP3"])
        self.checkbox_MP3.toggled.connect(self.update_checkbox_MP3)

        self.checkbox_MP4 = QCheckBox("MP4", self.centralwidget)
        self.checkbox_MP4.setGeometry(QtCore.QRect(90, 365, 60, 30))
        self.checkbox_MP4.setChecked(self.selected_formats["MP4"])
        self.checkbox_MP4.toggled.connect(self.update_checkbox_MP4)

        self.checkbox_FLAC = QCheckBox("FLAC", self.centralwidget)
        self.checkbox_FLAC.setGeometry(QtCore.QRect(170, 365, 60, 30))
        self.checkbox_FLAC.setChecked(self.selected_formats["FLAC"])
        self.checkbox_FLAC.toggled.connect(self.update_checkbox_FLAC)

        self.checkbox_WAV = QCheckBox("WAV", self.centralwidget)
        self.checkbox_WAV.setGeometry(QtCore.QRect(250, 365, 60, 30))
        self.checkbox_WAV.setChecked(self.selected_formats["WAV"])
        self.checkbox_WAV.toggled.connect(self.update_checkbox_WAV)

        self.checkbox_JPG = QCheckBox("JPG", self.centralwidget)
        self.checkbox_JPG.setGeometry(QtCore.QRect(330, 365, 60, 30))
        self.checkbox_JPG.setChecked(self.selected_formats["JPG"])
        self.checkbox_JPG.toggled.connect(self.update_checkbox_JPG)

        # 第二行：图片和文档格式
        self.checkbox_PNG = QCheckBox("PNG", self.centralwidget)
        self.checkbox_PNG.setGeometry(QtCore.QRect(10, 395, 60, 30))
        self.checkbox_PNG.setChecked(self.selected_formats["PNG"])
        self.checkbox_PNG.toggled.connect(self.update_checkbox_PNG)

        self.checkbox_PDF = QCheckBox("PDF", self.centralwidget)
        self.checkbox_PDF.setGeometry(QtCore.QRect(90, 395, 60, 30))
        self.checkbox_PDF.setChecked(self.selected_formats["PDF"])
        self.checkbox_PDF.toggled.connect(self.update_checkbox_PDF)

        self.checkbox_TXT = QCheckBox("TXT", self.centralwidget)
        self.checkbox_TXT.setGeometry(QtCore.QRect(170, 395, 60, 30))
        self.checkbox_TXT.setChecked(self.selected_formats["TXT"])
        self.checkbox_TXT.toggled.connect(self.update_checkbox_TXT)

        self.checkbox_VTT = QCheckBox("VTT", self.centralwidget)
        self.checkbox_VTT.setGeometry(QtCore.QRect(250, 395, 60, 30))
        self.checkbox_VTT.setChecked(self.selected_formats["VTT"])
        self.checkbox_VTT.toggled.connect(self.update_checkbox_VTT)

        self.checkbox_LRC = QCheckBox("LRC", self.centralwidget)
        self.checkbox_LRC.setGeometry(QtCore.QRect(330, 395, 60, 30))
        self.checkbox_LRC.setChecked(self.selected_formats["LRC"])
        self.checkbox_LRC.toggled.connect(self.update_checkbox_LCR)

        # # 开始下载按钮
        # self.down_start_button = QPushButton("Start", self.centralwidget)
        # self.down_start_button.setGeometry(QtCore.QRect(10, 250, 80, 30))
        # self.down_start_button.clicked.connect(self.down_start)
        # # 停止下载按钮
        # self.down_stop_button = QPushButton("Stop", self.centralwidget)
        # self.down_stop_button.setGeometry(QtCore.QRect(100, 250, 80, 30))
        # self.down_stop_button.clicked.connect(self.down_stop)
        # self.down_stop_button.setEnabled(False)
        # # 打开下载页面按钮
        # self.down_list_page_button = QPushButton("down page", self.centralwidget)
        # self.down_list_page_button.setGeometry(QtCore.QRect(280, 250, 80, 30))
        # self.down_list_page_button.clicked.connect(self.open_download_page)
        # self.down_list_page_button.setEnabled(True)
        self.set_data()

        # 连接语言切换信号
        self.language_changed.connect(self.on_language_changed)
        
        # 初始化语言显示
        self.update_language()

    def on_language_changed(self, language_code):
        """响应语言切换信号"""
        self.update_language()

    def save_open_proxy(self):
        self.conf.write_open_proxy('True' if self.open_proxy.isChecked() else 'False')

    def update_checkbox_MP3(self):
        self.selected_formats['MP3'] = not self.selected_formats['MP3']  # 更新字典中的值
        if self.selected_formats['MP3']:
            self.conf.write_downfile_type('MP3', 'true')
        else:
            self.conf.write_downfile_type('MP3', 'false')

    def update_checkbox_MP4(self):
        self.selected_formats['MP4'] = not self.selected_formats['MP4']
        if self.selected_formats['MP4']:
            self.conf.write_downfile_type('MP4', 'true')
        else:
            self.conf.write_downfile_type('MP4', 'false')
    def update_checkbox_FLAC(self):
        self.selected_formats['FLAC'] = not self.selected_formats['FLAC']
        if self.selected_formats['FLAC']:
            self.conf.write_downfile_type('FLAC', 'true')
        else:
            self.conf.write_downfile_type('FLAC', 'false')
    def update_checkbox_WAV(self):
        self.selected_formats['WAV'] = not self.selected_formats['WAV']
        if self.selected_formats['WAV']:
            self.conf.write_downfile_type('WAV', 'true')
        else:
            self.conf.write_downfile_type('WAV', 'false')
    def update_checkbox_JPG(self):
        self.selected_formats['JPG'] = not self.selected_formats['JPG']
        if self.selected_formats['JPG']:
            self.conf.write_downfile_type('JPG', 'true')
        else:
            self.conf.write_downfile_type('JPG', 'false')
    def update_checkbox_PNG(self):
        self.selected_formats['PNG'] = not self.selected_formats['PNG']
        if self.selected_formats['PNG']:
            self.conf.write_downfile_type('PNG', 'true')
        else:
            self.conf.write_downfile_type('PNG', 'false')
    def update_checkbox_PDF(self):
        self.selected_formats['PDF'] = not self.selected_formats['PDF']
        if self.selected_formats['PDF']:
            self.conf.write_downfile_type('PDF', 'true')
        else:
            self.conf.write_downfile_type('PDF', 'false')
    def update_checkbox_TXT(self):
        self.selected_formats['TXT'] = not self.selected_formats['TXT']
        if self.selected_formats['TXT']:
            self.conf.write_downfile_type('TXT', 'true')
        else:
            self.conf.write_downfile_type('TXT', 'false')
    def update_checkbox_VTT(self):
        self.selected_formats['VTT'] = not self.selected_formats['VTT']
        if self.selected_formats['VTT']:
            self.conf.write_downfile_type('VTT', 'true')
        else:
            self.conf.write_downfile_type('VTT', 'false')
    def update_checkbox_LCR(self):
        self.selected_formats['LRC'] = not self.selected_formats['LRC']
        if self.selected_formats['LRC']:
            self.conf.write_downfile_type('LRC', 'true')
        else:
            self.conf.write_downfile_type('LRC', 'false')

    def save_speed_limit(self):
        speed_limit = self.speed_limit.text()
        if re.match(r'^\d*\.?\d+$', speed_limit):  # 直接检查是否为小数
            self.conf.write_speed_limit(speed_limit)
        else:
            self.show_message_box(language_manager.get_text('invalid_decimal'), 'program')

    def save_proxy_address(self):
        address = self.proxy_address.text()
        if address:
            try:
                ipaddress.ip_address(address)
                self.conf.write_proxy_host(address)
            except ValueError:
                self.show_message_box(language_manager.get_text('invalid_ip'), 'program')

    def save_proxy_port(self):
        port = self.proxy_port.text()
        if port:
            try:
                if int(port) > 65535 or int(port) < 0:
                    self.show_message_box(language_manager.get_text('port_range_error'), 'program')
                else:
                    self.conf.write_proxy_port(port)
            except:
                self.show_message_box(language_manager.get_text('invalid_integer'), 'program')

    def save_max_retries(self):
        max_retries = self.max_retries.text()
        pattern = r'^\d+$'  # 修改正则表达式
        if bool(re.match(pattern, max_retries)):
            if re.match(r'^\d+$', max_retries):
                self.conf.write_max_retries(max_retries)
        else:
            self.show_message_box(language_manager.get_text('invalid_integer'), 'program')

    def save_timeout(self):
        timeout = self.timeout.text()
        if re.match(r'^\d+$', timeout):  # 直接检查是否为整数
            self.conf.write_timeout(timeout)
        else:
            self.show_message_box(language_manager.get_text('invalid_integer'), 'program')

        self.conf.write_timeout(timeout)

    def save_min_speed(self):
        min_speed = self.min_speed.text()
        if re.match(r'^\d+$', min_speed):  # 检查是否为整数
            self.conf.write_min_speed(min_speed)
        else:
            self.show_message_box(language_manager.get_text('invalid_integer'), 'program')

    def save_min_speed_check(self):
        min_speed_check = self.min_speed_check.text()
        if re.match(r'^\d+$', min_speed_check):  # 检查是否为整数
            self.conf.write_min_speed_check(min_speed_check)
        else:
            self.show_message_box(language_manager.get_text('invalid_integer'), 'program')

    def set_folder_for_name(self, text):
        # 将显示文本转换为对应的标识符
        naming_map = {
            language_manager.get_text('rj_naming'): 'rj_naming',
            language_manager.get_text('title_naming'): 'title_naming', 
            language_manager.get_text('rj_space_title_naming'): 'rj_space_title_naming',
            language_manager.get_text('rj_underscore_title_naming'): 'rj_underscore_title_naming'
        }
        naming_key = naming_map.get(text, 'title_naming')  # 默认为标题命名
        self.conf.write_folder_for_name(naming_key)

    def set_file_download_source(self, text):
        self.conf.write_website_course(text)


    def save_proxy_type(self, text):
        self.conf.write_proxy_type(text)


    def set_data(self):
        user_info = self.conf.read_asmr_user()
        down_conf = self.conf.read_download_conf()
        # proxy_conf = self.conf.read_proxy_conf()
        speed_limit = str(down_conf['speed_limit'])
        website_course = self.conf.read_website_course()
        self.user_name.setText(user_info["username"])
        self.password.setText(user_info["passwd"])
        self.speed_limit.setText(speed_limit)
        self.down_path.setText(down_conf['download_path'])
        self.max_retries.setText(str(down_conf['max_retries']))
        self.timeout.setText(str(down_conf['timeout']))
        self.min_speed.setText(str(down_conf['min_speed']))
        self.min_speed_check.setText(str(down_conf['min_speed_check']))
        # 设置命名方式值 - 使用标识符映射到索引
        folder_for_name = self.conf.read_name()
        naming_index_map = {
            'rj_naming': 0,
            'title_naming': 1,
            'rj_space_title_naming': 2,
            'rj_underscore_title_naming': 3
        }
        index = naming_index_map.get(folder_for_name, 1)  # 默认为标题命名
        self.folder_name_type_combo_box.setCurrentIndex(index)
        self.proxy_port.setText(str(self.proxy_conf['port']))
        self.proxy_address.setText(str(self.proxy_conf['host']))
        if self.proxy_conf['proxy_type'] == 'http':
            self.set_proxy_type.setCurrentIndex(0)
        elif self.proxy_conf['proxy_type'] == 'https':
            self.set_proxy_type.setCurrentIndex(1)
        elif self.proxy_conf['proxy_type'] == 'socks5':
            self.set_proxy_type.setCurrentIndex(2)
        elif self.proxy_conf['proxy_type'] == 'socks4':
            self.set_proxy_type.setCurrentIndex(3)
        if website_course == 'Original':
            self.file_download_source.setCurrentIndex(0)
        elif website_course == 'Mirror-1':
            self.file_download_source.setCurrentIndex(1)
        elif website_course == 'Mirror-2':
            self.file_download_source.setCurrentIndex(2)
        elif website_course == 'Mirror-3':
            self.file_download_source.setCurrentIndex(3)

    def save_download_path(self):
        download_path = QFileDialog.getExistingDirectory(self, language_manager.get_text('select_download_path'))
        if download_path:
            self.down_path.setText(download_path)
            speed_limit = self.speed_limit.text()
            self.conf.write_download_conf(speed_limit, download_path)
            # 发出下载路径更改信号
            self.download_path_changed.emit()
            print(f"{language_manager.get_text('path_config_updated')}: {download_path}")

    def save_user(self):
        user_name = self.user_name.text()
        password = self.password.text()
        
        # 检查用户名和密码是否为空
        if not user_name or not password:
            self.show_message_box(language_manager.get_text('please_enter_username_password'), language_manager.get_text('validation_failed'))
            return
        
        # 禁用登录按钮，防止重复点击
        self.user_conf_save_button.setEnabled(False)
        self.user_conf_save_button.setText(language_manager.get_text('logging_in'))
        
        # 创建登录线程
        self.login_thread = LoginThread(user_name, password)
        self.login_thread.login_finished.connect(self.on_login_finished)
        self.login_thread.finished.connect(self.login_thread.deleteLater)
        self.login_thread.start()
    
    def on_login_finished(self, success, message):
        """登录完成回调"""
        # 恢复登录按钮状态
        self.user_conf_save_button.setEnabled(True)
        self.user_conf_save_button.setText(language_manager.get_text('login'))
        
        if success:
            self.show_message_box(language_manager.get_text('login_success'), "from asmr.one")
        else:
            self.show_message_box(message, "from asmr.one")

    def open_download_page(self):
        from src.UI.download_page import DownloadPage
        if not hasattr(self, 'download_page') or not self.download_page:
            self.download_page = DownloadPage()
        self.download_page.show()
        self.download_page.raise_()
        self.download_page.activateWindow()

    def update_language(self):
        """更新界面语言显示"""
        # 更新窗口标题
        self.setWindowTitle(language_manager.get_text('app_title'))
        
        # 更新所有标签文本
        self.download_path_label.setText(language_manager.get_text('download_path_settings'))
        self.network_settings_label.setText(language_manager.get_text('network_settings'))
        self.speed_limit_desc_label.setText(language_manager.get_text('download_speed_limit'))
        self.speed_limit_label.setText(language_manager.get_text('mb_per_s'))
        self.download_source_label.setText(language_manager.get_text('download_source'))
        self.open_proxy.setText(language_manager.get_text('use_proxy'))
        self.login_label.setText(language_manager.get_text('user_login'))
        self.download_settings_label.setText(language_manager.get_text('download_settings'))
        self.max_retries_desc_label.setText(language_manager.get_text('retry_count'))
        self.max_retries_label.setText(language_manager.get_text('times'))
        self.timeout_desc_label.setText(language_manager.get_text('timeout_time'))
        self.time_out_label.setText(language_manager.get_text('second'))
        self.min_speed_desc_label.setText(language_manager.get_text('min_speed'))
        self.min_speed_label.setText(language_manager.get_text('kb_per_s'))
        self.min_speed_check_desc_label.setText(language_manager.get_text('check_interval'))
        self.min_speed_check_label.setText(language_manager.get_text('second'))
        self.label.setText(language_manager.get_text('folder_naming'))
        self.file_types_label.setText(language_manager.get_text('file_type_selection'))
        
        # 更新按钮文本
        self.path_conf_save_button.setText(language_manager.get_text('select'))
        self.user_conf_save_button.setText(language_manager.get_text('login'))
        
        # 更新输入框占位符文本
        self.down_path.setPlaceholderText(language_manager.get_text('download_path'))
        self.speed_limit.setPlaceholderText(language_manager.get_text('speed'))
        self.proxy_address.setPlaceholderText(language_manager.get_text('proxy_address'))
        self.proxy_port.setPlaceholderText(language_manager.get_text('port'))
        self.user_name.setPlaceholderText(language_manager.get_text('user_name'))
        self.password.setPlaceholderText(language_manager.get_text('password'))
        self.max_retries.setPlaceholderText(language_manager.get_text('max_retries'))
        self.timeout.setPlaceholderText(language_manager.get_text('timeout'))
        
        # 更新下拉框选项
        current_folder_index = self.folder_name_type_combo_box.currentIndex()
        self.folder_name_type_combo_box.clear()
        self.folder_name_type_combo_box.addItem(language_manager.get_text('rj_naming'))
        self.folder_name_type_combo_box.addItem(language_manager.get_text('title_naming'))
        self.folder_name_type_combo_box.addItem(language_manager.get_text('rj_space_title_naming'))
        self.folder_name_type_combo_box.addItem(language_manager.get_text('rj_underscore_title_naming'))
        self.folder_name_type_combo_box.setCurrentIndex(current_folder_index)

    def show_message_box(self, message, title):
        """显示消息框"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.exec()
