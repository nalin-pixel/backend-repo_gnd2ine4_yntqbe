"""
Database Schemas for Video Sharing MVP

Each Pydantic model maps to a MongoDB collection. The collection name is the lowercase of the class name.

Collections:
- User -> user
- Video -> video
- Comment -> comment
- Subscription -> subscription
- Like -> like
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List


class User(BaseModel):
    username: str = Field(..., min_length=3, max_length=30)
    email: EmailStr
    password_hash: str = Field(..., description="Bcrypt hash")
    avatar_url: Optional[str] = None
    bio: Optional[str] = None


class Video(BaseModel):
    user_id: str = Field(..., description="Owner user id as string")
    title: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    video_url: str
    thumbnail_url: Optional[str] = None
    views_count: int = 0
    likes_count: int = 0


class Comment(BaseModel):
    video_id: str
    user_id: str
    text: str = Field(..., min_length=1, max_length=500)


class Subscription(BaseModel):
    channel_id: str = Field(..., description="The user id of the channel being subscribed to")
    subscriber_id: str = Field(..., description="The user id of the subscriber")


class Like(BaseModel):
    video_id: str
    user_id: str
    value: int = Field(1, description="1 for like; -1 for dislike (future)")
