from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from app.db.connection import get_db
from app.db.models import User
from app.auth.utils import SECRET_KEY, ALGORITHM

# Define how we extract token from request headers
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

#Verify and decode JWT token
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise credentials_exception

    return user


#Check if current user is a citizen (role = user)
def require_citizen(current_user: User = Depends(get_current_user)):
    role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role_val != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Citizen access required"
        )
    return current_user


#Check if current user is an officer
def require_officer(current_user: User = Depends(get_current_user)):
    role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role_val != "officer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Officer access required"
        )
    return current_user


#Check if current user is an admin
def require_admin(current_user: User = Depends(get_current_user)):
    role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role_val != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


#Check if current user is an officer or admin
def require_officer_or_admin(current_user: User = Depends(get_current_user)):
    role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role_val not in ["admin", "officer"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Officer or Admin access required"
        )
    return current_user


def get_actor_role_str(user: User) -> str:
    """Returns canonical role string ('citizen', 'officer', 'admin')."""
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role_val == "user":
        return "citizen"
    return role_val


def enforce_grievance_access(grievance, current_user: User, action: str = "view"):
    """
    Enforces server-side object ownership and role-based boundaries.
    - Admin: universal access
    - Citizen: restricted strictly to own grievances
    - Officer: restricted strictly to assigned grievances
    """
    role = get_actor_role_str(current_user)
    if role == "admin":
        return

    if role == "citizen":
        if grievance.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Citizens can only {action} their own grievances"
            )
        return

    if role == "officer":
        if grievance.assigned_officer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Officers can only {action} grievances assigned to their queue"
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Not authorized to {action} this grievance"
    )

