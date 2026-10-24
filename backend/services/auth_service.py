import logging

import mysql.connector
from fastapi import HTTPException
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from db import get_db_connection

logger = logging.getLogger(__name__)
password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False

    try:
        return password_hasher.verify(password, stored_hash)
    except UnknownHashError:
        logger.warning("Stored password hash is invalid")
        return False


def register_user(name: str, email: str, password: str) -> dict:
    connection = get_db_connection()
    if connection is None:
        raise HTTPException(status_code=503, detail="Database is unavailable.")

    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO users (name, email, password_hash)
            VALUES (%s, %s, %s)
            """,
            (name, email, hash_password(password)),
        )
        user = {"id": cursor.lastrowid, "name": name, "email": email}
        connection.commit()
        return user
    except mysql.connector.IntegrityError:
        connection.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account with this email already exists.",
        )
    except mysql.connector.Error as error:
        connection.rollback()
        logger.error("Account registration database failure (%s)", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Authentication storage is unavailable. Check the database migration.",
        )
    except Exception as error:
        connection.rollback()
        logger.error("Account registration failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Account registration is temporarily unavailable.",
        )
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def authenticate_user(email: str, password: str) -> dict:
    connection = get_db_connection()
    if connection is None:
        raise HTTPException(status_code=503, detail="Database is unavailable.")

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()
        if user is None or not verify_password(password, user["password_hash"]):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return {"id": user["id"], "name": user["name"], "email": user["email"]}
    except HTTPException:
        raise
    except mysql.connector.Error as error:
        logger.error("Account login database failure (%s)", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Authentication storage is unavailable. Check the database migration.",
        )
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def get_user_by_id(user_id: int) -> dict | None:
    connection = get_db_connection()
    if connection is None:
        raise HTTPException(status_code=503, detail="Database is unavailable.")

    cursor = None
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, name, email FROM users WHERE id = %s",
            (user_id,),
        )
        return cursor.fetchone()
    except mysql.connector.Error as error:
        logger.error("Account lookup database failure (%s)", type(error).__name__)
        raise HTTPException(status_code=503, detail="Authentication storage is unavailable.")
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()


def reset_password(email: str, new_password: str) -> None:
    connection = get_db_connection()
    if connection is None:
        raise HTTPException(status_code=503, detail="Database is unavailable.")

    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="No account found with this email.")
        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE email = %s",
            (hash_password(new_password), email),
        )
        connection.commit()
    except HTTPException:
        raise
    except mysql.connector.Error as error:
        connection.rollback()
        logger.error("Password reset database failure (%s)", type(error).__name__)
        raise HTTPException(status_code=503, detail="Password reset is temporarily unavailable.")
    finally:
        if cursor is not None:
            cursor.close()
        connection.close()