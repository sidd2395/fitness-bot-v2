from sqlalchemy.orm import Session

from app.db.models import User


def delete_user(user_id: int, db: Session) -> bool:
    """Delete a user and every row they own. Returns False if no such user."""
    user = db.get(User, user_id)
    if user is None:
        return False
    db.delete(user)  # ORM cascade removes profile, issues, checkins, raw_messages
    db.commit()
    return True
