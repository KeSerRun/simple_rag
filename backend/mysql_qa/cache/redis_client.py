from base.config import conf
from base.logger import logger
import redis
import json

class RedisClient:
    def __init__(self):
        try:
            # 创建 Redis 连接
            self.redis_client = redis.Redis(
                host = conf.redis_host,
                port = conf.redis_port,
                password = conf.redis_password if conf.redis_password is True else None,
                db = conf.redis_db,
                decode_responses = True  # 确保返回字符串而不是字节
            )
            print(conf.redis_password if conf.redis_password else None)
            # 连接成功日志
            logger.info("成功连接到 Redis 数据库")
        except Exception as e:
            # 连接失败日志
            logger.error(f"连接 Redis 数据库失败: {e}")
            raise

    def set(self, key, value, ex=None):
        """设置键值对"""
        try:
            # 将value转换为JSON字符串
            value_json = json.dumps(value)
            # 存储JSON字符串到Redis
            self.redis_client.set(key, value_json, ex=ex)
            return True
        except Exception as e:
            logger.error(f"设置键值对{key}:{value}失败: {e}")
            return False

    def get(self, key):
        """获取键对应的值"""
        try:
            # 从Redis获取JSON字符串并转换回Python对象
            value_json = self.redis_client.get(key)
            if value_json:
                return json.loads(value_json)
        except Exception as e:
            # 记录键值对失败日志
            logger.error(f"获取键{key}的值失败: {e}")
        return None

    def __del__(self):
        # 关闭 Redis 连接
        try:
            self.redis_client.close()
            logger.info("成功关闭 Redis 连接")
        except Exception as e:
            logger.error(f"关闭 Redis 连接失败: {e}")
            raise

if __name__ == "__main__":
    # 创建 Redis 客户端实例
    redis_client = RedisClient()
    # 测试设置和获取键值对
    redis_client.set("test_key", {"name": "EduRAG", "type": "QA System"})
    value = redis_client.get("test_key")
    print(value)  # 输出: {'name': 'EduRAG', 'type': 'QA System'}
