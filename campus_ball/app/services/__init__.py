"""
业务服务包
====================================================================
说明：本文件刻意保持「空」
原因：reputation / blacklist 等服务之间互相引用，
若在 __init__ 里 import 会造成循环导入。
请直接按模块引用，例如：
    from app.services import reputation
    from app.services.reputation import settle_on_checkin
====================================================================
"""
