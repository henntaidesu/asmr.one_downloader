import sys
from src.read_conf import ReadConf
import sqlite3


def TrimString(Str):
    # if '\n' in Str:
    #     Str = Str.replace('\n', ' ')
    # if ' ' in Str:
    #     Str = Str.replace(' ', '')
    # if '/' in Str:
    #     Str = Str.replace('/', ' ')
    if "'" in Str:
        Str = Str.replace("'", "\\'")
    if '"' in Str:
        Str = Str.replace('"', '\\"')
    return Str


class MySQLDB:
    def __init__(self):
        read_db_conf = ReadConf()
        self.db = read_db_conf.read_database()

    def insert(self, sql):
        # 只关闭游标，不关闭连接：否则同一实例后续 update/select/delete 会因连接已关而报错
        cursor = self.db.cursor()
        cursor.execute(sql)
        self.db.commit()
        cursor.close()
        return True

    def close(self):
        """显式关闭数据库连接"""
        if hasattr(self, 'db') and self.db:
            self.db.close()

    def update(self, sql):
        cursor = self.db.cursor()
        cursor.execute(sql)
        self.db.commit()
        cursor.close()
        return True


    def select(self, sql):
        cursor = self.db.cursor()
        cursor.execute(sql)
        result = cursor.fetchall()
        cursor.close()
        return True, result


    def delete(self, sql):
        cursor = self.db.cursor()
        cursor.execute(sql)
        self.db.commit()
        cursor.close()



# class SQLiteDB:
#     def __init__(self):
#         self.db = None
#         self.db_path = "db.db"
#         self.connect_db()

#     def connect_db(self):
#         """连接SQLite数据库"""
#         try:
#             self.db = sqlite3.connect(self.db_path)
#         except sqlite3.Error as e:
#             print(f"数据库连接失败: {str(e)}")
#             self.db = None
#             raise sqlite3.Error(f"数据库连接失败: {str(e)}")

#     def execute_query(self, sql, query_type='select'):
#         """
#         执行SQL查询，根据类型返回不同的结果。
#         query_type: select, insert, update, delete
#         """
#         try:
#             cursor = self.db.cursor()
#             cursor.execute(sql)

#             if query_type == 'select':
#                 result = cursor.fetchall()
#                 return True, result
#             elif query_type in ['insert', 'update', 'delete']:
#                 self.db.commit()  # 对于修改操作，提交更改
#                 return True
#         except sqlite3.Error as e:
#             print(f"数据库操作失败: {str(e)}", 'error')
#             return False


#     def insert(self, sql):
#         return self.execute_query(sql, 'insert')

#     def update(self, sql):
#         return self.execute_query(sql, 'update')

#     def select(self, sql):
#         return self.execute_query(sql, 'select')

#     def delete(self, sql):
#         return self.execute_query(sql, 'delete')

#     def close_connection(self):
#         if hasattr(self, 'db') and self.db:
#             self.db.close()
