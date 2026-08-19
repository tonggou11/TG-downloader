"""
License 层 — 抽象接口。

当前使用 StubLicenseManager（永久有效），未来替换为 RemoteLicenseManager
即可接入会员系统。应用层只依赖 LicenseManager 抽象，不关心实现。
"""

from abc import ABC, abstractmethod


class LicenseManager(ABC):
    """会员验证抽象接口。"""

    @abstractmethod
    def check_permission(self) -> dict:
        """
        检查当前用户的权限。

        返回:
            {
                "allowed": bool,           # 是否允许使用
                "tier": str,               # "free" | "pro" | "enterprise"
                "remaining_channels": int | None,  # 剩余可下载频道数（None=无限）
                "expires_at": str | None,  # 到期时间 ISO 格式
                "reason": str | None,      # 拒绝原因（allowed=False 时）
            }
        """
        ...

    @abstractmethod
    def activate(self, code: str) -> bool:
        """激活码兑换，成功返回 True。"""
        ...

    @abstractmethod
    def get_user_info(self) -> dict:
        """获取当前用户信息。"""
        ...
