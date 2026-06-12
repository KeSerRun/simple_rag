from base.config import conf
from base.logger import logger
import pandas as pd
import pymysql

class MySQLClient:
    def __init__(self):
        try:
            # 数据表列表
            self.tables = ['user_password', 'user_session', 'qa_pairs', 'conversion_history']
            # 连接 MySQL 数据库
            self.connection = pymysql.connect(
                host=conf.mysql_host,
                port=conf.mysql_port,
                user=conf.mysql_user,
                password=conf.mysql_password,
                database=conf.mysql_database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            # 创建游标对象
            self.cursor = self.connection.cursor()
            # 初始化数据表
            self.initialize_tables()
            # 连接成功日志
            logger.info("成功连接到 MySQL 数据库")
        except Exception as e:
            # 连接失败日志
            logger.error(f"连接 MySQL 数据库失败: {e}")
            raise

## ----------------- 建表 ----------------- ##
    def create_user_password_table(self):
        # 创建用户表的 SQL 语句
        crate_table_sql = '''
        CREATE TABLE IF NOT EXISTS `user_password` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `username` VARCHAR(30) NOT NULL UNIQUE,
            `password` VARCHAR(30) NOT NULL,
            `role` VARCHAR(20) NOT NULL DEFAULT 'user',
            `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_username (username)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        '''    
        try:
            # 执行创建表的 SQL 语句
            self.cursor.execute(crate_table_sql)
            # 提交事务
            self.connection.commit()
            # 创建表成功日志
            logger.info("成功创建 user_password 表")
        except Exception as e:
            # 创建表失败日志
            logger.error(f"创建 user_password 表失败: {e}")
            raise

    def create_user_session_table(self):
        # 创建用户会话表的 SQL 语句
        crate_table_sql = '''
        CREATE TABLE IF NOT EXISTS `user_session` (
            `session_id` VARCHAR(36) PRIMARY KEY,
            `username` VARCHAR(255) NOT NULL,
            `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (username) REFERENCES user_password(username)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        '''    
        try:
            # 执行创建表的 SQL 语句
            self.cursor.execute(crate_table_sql)
            # 提交事务
            self.connection.commit()
            # 创建表成功日志
            logger.info("成功创建 user_session 表")
        except Exception as e:
            # 创建表失败日志
            logger.error(f"创建 user_session 表失败: {e}")
            raise

    def create_qa_table(self):
        # 创建 qa_pairs 表的 SQL 语句
        crate_table_sql = '''
        CREATE TABLE IF NOT EXISTS `qa_pairs` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `question` TEXT NOT NULL,
            `answer` TEXT NOT NULL,
            INDEX idx_question (question(511))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        '''    
        try:
            # 执行创建表的 SQL 语句
            self.cursor.execute(crate_table_sql)
            # 提交事务
            self.connection.commit()
            # 创建表成功日志
            logger.info("成功创建 qa_pairs 表")
        except Exception as e:
            # 创建表失败日志
            logger.error(f"创建 qa_pairs 表失败: {e}")
            raise

    def create_conversion_table(self):
        # 创建对话历史表的 SQL 语句
        crate_table_sql = '''
        CREATE TABLE IF NOT EXISTS `conversion_history` (
            `id` INT AUTO_INCREMENT PRIMARY KEY,
            `session_id` VARCHAR(36) NOT NULL,
            `user` TEXT NOT NULL,
            `assistant` TEXT NOT NULL,
            `timestamp` TIMESTAMP NOT NULL,
            INDEX idx_session_id (session_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        '''    
        try:
            # 执行创建表的 SQL 语句
            self.cursor.execute(crate_table_sql)
            # 提交事务
            self.connection.commit()
            # 创建表成功日志
            logger.info("成功创建 conversion_history 表")
        except Exception as e:
            # 创建表失败日志
            logger.error(f"创建 conversion_history 表失败: {e}")
            raise

    # 检查表是否存在
    def check_table_exists(self, table_name):
        check_table_sql = '''
        SHOW TABLES LIKE %s;
        '''
        try:
            self.cursor.execute(check_table_sql, (table_name,))
            result = self.cursor.fetchone()
            return result is not None
        except Exception as e:
            logger.error(f"检查表 {table_name} 是否存在失败: {e}")
            raise

    # 初始化数据表
    def initialize_tables(self):
        for table in self.tables:
            if not self.check_table_exists(table):
                if table == 'qa_pairs':
                    self.create_qa_table()
                    logger.info(f"表 {table} 不存在，已创建")
                elif table == 'conversion_history':
                    self.create_conversion_table()
                    logger.info(f"表 {table} 不存在，已创建")
                elif table == 'user_password':
                    self.create_user_password_table()
                    logger.info(f"表 {table} 不存在，已创建")
                elif table == 'user_session':
                    self.create_user_session_table()
                    logger.info(f"表 {table} 不存在，已创建")
            else:
                logger.info(f"表 {table} 已存在，无需创建")

## ----------------- 用户操作 ----------------- ##
    def insert_user(self, username, password, role='user'):
        # 插入用户的 SQL 语句
        insert_sql = '''
        INSERT INTO `user_password` (username, password, role) VALUES (%s, %s, %s);
        '''
        try:
            # 执行插入数据的 SQL 语句
            self.cursor.execute(insert_sql, (username, password, role))
            # 提交事务
            self.connection.commit()
            # 插入数据成功日志
            logger.info(f"成功插入用户: {username}")
            return True
        except Exception as e:
            # 插入数据失败日志
            logger.error(f"插入用户失败: {e}")
            return False

    def delete_user(self, username):
        # 删除指定用户名的用户的 SQL 语句
        delete_sql = '''
        DELETE FROM `user_password` 
        WHERE username = %s;
        '''
        try:
            # 执行删除数据的 SQL 语句
            self.cursor.execute(delete_sql, (username,))
            # 提交事务
            self.connection.commit()
            # 删除数据成功日志
            logger.info(f"成功删除用户: {username}")
            return True
        except Exception as e:
            # 删除数据失败日志
            logger.error(f"删除用户失败: {e}")
            return False

    def insert_session(self, session_id, username):
        # 插入用户会话的 SQL 语句
        insert_sql = '''
        INSERT INTO `user_session` (session_id, username) VALUES (%s, %s);
        '''
        try:
            # 执行插入数据的 SQL 语句
            self.cursor.execute(insert_sql, (session_id, username))
            # 提交事务
            self.connection.commit()
            # 插入数据成功日志
            logger.info(f"成功插入用户会话: session_id={session_id}, username={username}")
            return True
        except Exception as e:
            # 插入数据失败日志
            logger.error(f"插入用户会话失败: {e}")
            return False

    def delete_session(self, session_id):
        # 删除指定 session_id 的用户会话的 SQL 语句
        delete_sql = '''
        DELETE FROM `user_session` 
        WHERE session_id = %s;
        '''
        try:
            # 执行删除数据的 SQL 语句
            self.cursor.execute(delete_sql, (session_id,))
            # 提交事务
            self.connection.commit()
            # 删除数据成功日志
            logger.info(f"成功删除用户会话: session_id={session_id}")
            return True
        except Exception as e:
            # 删除数据失败日志
            logger.error(f"删除用户会话失败: {e}")
            return False

    def fetch_sessions_by_username(self, username):
        # 根据用户名查询对应会话 ID 的 SQL 语句
        select_sql = 'SELECT session_id FROM `user_session` WHERE username = %s;'
        try:
            # 执行查询数据的 SQL 语句
            self.cursor.execute(select_sql, (username,))
            # 获取查询结果
            result = self.cursor.fetchall()
            # 查询数据成功日志
            logger.info(f"成功根据用户名查询对应会话 ID: {username}")
            return [row['session_id'] for row in result] if result else None
        except Exception as e:
            # 查询数据失败日志
            logger.error(f"根据用户名查询对应会话 ID 失败: {e}")
            return None

    def check_user_credentials(self, username, password):
        # 根据用户名和密码查询用户的 SQL 语句
        select_sql = 'SELECT username,role FROM `user_password` WHERE username = %s AND password = %s;'
        try:
            # 执行查询数据的 SQL 语句
            self.cursor.execute(select_sql, (username, password))
            # 获取查询结果
            result = self.cursor.fetchone()
            # 查询数据成功日志
            if result:
                logger.info(f"成功验证用户凭据: {username}")
                return result
            return False
        except Exception as e:
            # 查询数据失败日志
            logger.error(f"验证用户凭据失败: {e}")
            return False


## ----------------- 问答对操作 ----------------- ##
    def insert_qa_pair(self, question, answer, log=True):
        # 检查问题是否已存在
        check_sql = 'SELECT 1 FROM `qa_pairs` WHERE question = %s;'
        self.cursor.execute(check_sql, (question,))
        if self.cursor.fetchone():
            logger.info(f"问题 '{question}' 已存在，跳过插入")
            return False

        # 如果不存在该问题，则插入问答对的 SQL 语句
        insert_sql = '''
        INSERT INTO `qa_pairs` (question, answer) VALUES (%s, %s);
        '''
        try:
            # 执行插入数据的 SQL 语句
            self.cursor.execute(insert_sql, (question, answer))
            # 提交事务
            self.connection.commit()
            # 插入数据成功日志
            if log:
                logger.info("成功插入问答对")
            return True
        except Exception as e:
            # 插入数据失败日志
            logger.error(f"插入问答对失败: {e}")
            return False

    def insert_qa_pairs_from_csv(self,csv_file):
        try:
            # 读取 CSV 文件
            df = pd.read_csv(csv_file, encoding='utf-8')
            # 遍历 DataFrame 中的每一行，插入问答对
            for index, row in df.iterrows():
                self.insert_qa_pair(
                    row[conf.question_head_name], 
                    row[conf.answer_head_name], log=False)
            # 插入数据成功日志
            logger.info(f"成功从 {csv_file} 插入问答对")
            return True
        except Exception as e:
            # 插入数据失败日志
            logger.error(f"从 {csv_file} 插入问答对失败: {e}")
            return False

    def delete_all_qa_pairs(self):
        # 删除 qa_pairs 表中所有数据的 SQL 语句
        delete_sql = 'DELETE FROM `qa_pairs`;'
        try:
            # 执行删除数据的 SQL 语句
            self.cursor.execute(delete_sql)
            # 提交事务
            self.connection.commit()
            # 删除数据成功日志
            logger.info(f"成功删除 qa_pairs 表中的所有数据")
            return True
        except Exception as e:
            # 删除数据失败日志
            logger.error(f"删除 qa_pairs 表中的所有数据失败: {e}")
            return False

    def fetch_all_questions(self):
        # 查询 qa_pairs 表中所有问题的 SQL 语句
        select_sql = 'SELECT question FROM `qa_pairs`;'
        try:
            # 执行查询数据的 SQL 语句
            self.cursor.execute(select_sql)
            # 获取所有查询结果
            questions = self.cursor.fetchall()
            # 查询数据成功日志
            logger.info(f"成功查询所有问题")
            return questions
        except Exception as e:
            # 查询数据失败日志
            logger.error(f"查询所有问题失败: {e}")
            return None

    def fetch_answer_by_question(self, question):
        # 根据问题查询对应答案的 SQL 语句
        select_sql = 'SELECT answer FROM `qa_pairs` WHERE question = %s;'
        try:
            # 执行查询数据的 SQL 语句
            self.cursor.execute(select_sql, (question,))
            # 获取查询结果
            result = self.cursor.fetchone()
            # 查询数据成功日志
            logger.info(f"成功根据问题查询对应答案: {question}")
            return result['answer'] if result else None
        except Exception as e:
            # 查询数据失败日志
            logger.error(f"根据问题查询对应答案失败: {e}")
            return None

## ----------------- 对话历史操作 ----------------- ##
    def get_session_history(self, session_id: str)-> list:
        # 根据 session_id 查询对话历史的 SQL 语句
        select_sql = '''
        SELECT user, assistant 
        FROM `conversion_history` 
        WHERE session_id = %s 
        ORDER BY timestamp
        ASC;    # 按照时间戳升序排序，确保返回的对话历史是按照时间顺序排列的
        '''
        try:
            # 执行查询数据的 SQL 语句
            self.cursor.execute(select_sql, (session_id,))
            # 获取查询结果
            history = self.cursor.fetchall()
            # 查询数据成功日志
            logger.info(f"session_id={session_id}, 成功查询对话历史")
            return history
        except Exception as e:
            # 查询数据失败日志
            logger.error(f"session_id={session_id}, 根据 session_id 查询对话历史失败: {e}")
            return None

    def insert_session_history(self, session_id: str, user: str, assistant: str) -> bool:
        # 插入对话历史的 SQL 语句
        insert_sql = '''
        INSERT INTO `conversion_history` 
        (session_id, user, assistant, timestamp) 
        VALUES (%s, %s, %s, NOW());
        '''
        try:
            # 执行插入数据的 SQL 语句
            self.cursor.execute(insert_sql, (session_id, user, assistant))
            # 提交事务
            self.connection.commit()
            # 插入数据成功日志
            logger.info(f"session_id={session_id}, 成功插入对话历史")
            return True
        except Exception as e:
            # 插入数据失败日志
            logger.error(f"session_id={session_id}, 插入对话历史失败: {e}")
            return False

    def delete_session_history(self, session_id: str):
        # 删除指定 session_id 的对话历史的 SQL 语句
        delete_sql = """
        DELETE FROM `conversion_history` 
        WHERE session_id = %s;
        """
        try:
            # 执行删除数据的 SQL 语句
            self.cursor.execute(delete_sql, (session_id,))
            # 提交事务
            self.connection.commit()
            # 删除数据成功日志
            logger.info(f"session_id={session_id}, 成功删除对话历史")
            return True
        except Exception as e:
            # 删除数据失败日志
            logger.error(f"session_id={session_id}, 删除对话历史失败: {e}")
            return False


## ----------------- 析构函数 ----------------- ##
    def __del__(self):
        # 关闭游标和数据库连接
        try:
            self.cursor.close()
            self.connection.close()
            # 关闭连接日志
            logger.info("成功关闭 MySQL 数据库连接")
        except Exception as e:
            # 关闭连接失败日志
            logger.error(f"关闭 MySQL 数据库连接失败: {e}")
            raise

if __name__ == "__main__":
    # 创建 MySQL 客户端实例
    mysql_client = MySQLClient()
    # 创建 qa_pairs 表
    mysql_client.create_qa_table()
    # 插入示例问答对
    mysql_client.insert_qa_pair("人工智能", "什么是人工智能？", "人工智能是指使计算机能够执行通常需要人类智能才能完成的任务的技术。")
    # 从 CSV 文件插入问答对
    # mysql_client.insert_qa_pairs_from_csv(conf.data_file)
    # 删除 qa_pairs 表中的所有数据
    # mysql_client.delete_all_qa_pairs()
    # 查询 qa_pairs 表中的所有问题
    questions = mysql_client.fetch_all_questions()
    print(questions)
    # 根据问题查询对应答案
    answer = mysql_client.fetch_answer_by_question("什么是人工智能？")
    print(answer)