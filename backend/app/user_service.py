from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .repositories import PortfolioRepository, UserRepository


class UserService:
    def __init__(self, session: Session):
        self.session = session
        self.user_repo = UserRepository(session)
        self.portfolio_repo = PortfolioRepository(session)

    def list_users(self):
        return self.user_repo.list_users()

    def require_user(self, user_id: str):
        user = self.user_repo.get(user_id)
        if not user:
            raise ValueError("User not found")
        return user

    def resolve_user_id(self, requested_user_id: str | None = None) -> str:
        normalized_user_id = (requested_user_id or "").strip()
        if normalized_user_id:
            return self.require_user(normalized_user_id).id

        users = self.user_repo.list_users()
        if not users:
            raise ValueError("No user available")
        return users[0].id

    def list_user_ids(self) -> list[str]:
        return self.user_repo.list_user_ids()

    def create_user(self, *, name: str, initial_cash: float):
        normalized_name = name.strip()
        if normalized_name == "":
            raise ValueError("User name is required")
        if self.user_repo.get_by_name(normalized_name):
            raise ValueError("User name already exists")

        user = self.user_repo.create(
            name=normalized_name,
            initial_cash=initial_cash,
        )
        self.portfolio_repo.add_cash_entry(
            user_id=user.id,
            entry_time=datetime.now(),
            entry_type="INITIAL",
            amount=user.initial_cash,
            balance_after=user.initial_cash,
            reference_type="UserAccountBootstrap",
        )
        return user
