"""
Stub License — 永久有效的本地 License。

当前版本实现，用户无需登录即可使用全部功能。
未来替换为 RemoteLicenseManager 联动后端会员系统。
"""

from license.base import LicenseManager


class StubLicenseManager(LicenseManager):
    """永久有效的本地 License（当前版本）。"""

    TIER = "enterprise"

    def check_permission(self) -> dict:
        return {
            "allowed": True,
            "tier": self.TIER,
            "remaining_channels": None,  # 无限
            "expires_at": None,
            "reason": None,
        }

    def activate(self, code: str) -> bool:
        # Stub 版本接受任何激活码
        return True

    def get_user_info(self) -> dict:
        return {
            "tier": self.TIER,
            "activated_at": "N/A",
            "machine_id": "N/A",
        }
