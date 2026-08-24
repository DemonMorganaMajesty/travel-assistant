"""密码安全工具：使用 bcrypt 哈希与校验。

用户密码哈希加密、密码校验；绝不存储明文密码，注册存哈希，登录比对哈希。
"""

import bcrypt


def hash_password(password: str) -> str:
    """密码加盐哈希，返回字符串形式哈希。
    bcrypt.gensalt() 自动生成随机盐值，盐会嵌入最终哈希字符串内部，
    数据库只需要存一个字段，不用单独存 salt。

    采用 bcrypt 实现密码加盐哈希，数据库只存储密码哈希，不保存明文密码；
    登录阶段进行哈希比对，提升账号存储安全。
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配。
    从数据库的 加盐哈希 提取出盐  盐+明文密码=?=加盐哈希
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
