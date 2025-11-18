import os
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from datetime import datetime
from bson import ObjectId

from database import db, create_document, get_documents

# Password hashing
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure upload directories exist
UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
VIDEO_DIR = os.path.join(UPLOAD_DIR, "videos")
THUMB_DIR = os.path.join(UPLOAD_DIR, "thumbnails")
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

# Mount static file serving
if not os.path.exists("static"):
    os.makedirs("static", exist_ok=True)
# We will symlink or map uploads directory under /static for URL access
app.mount("/static", StaticFiles(directory=UPLOAD_DIR), name="static")


# -------------------- Models --------------------
class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# -------------------- Helpers --------------------

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def to_str_id(doc):
    if not doc:
        return doc
    d = {**doc}
    if d.get("_id"):
        d["id"] = str(d.pop("_id"))
    # Convert datetime to isoformat
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def objid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id format")


# -------------------- Basic Routes --------------------
@app.get("/")
def read_root():
    return {"message": "Video Sharing Backend is running"}


@app.get("/test")
def test_database():
    info = {
        "backend": "running",
        "database_connected": False,
        "collections": []
    }
    try:
        if db is not None:
            info["database_connected"] = True
            info["collections"] = db.list_collection_names()
    except Exception as e:
        info["error"] = str(e)
    return info


# -------------------- Auth --------------------
@app.post("/auth/register")
def register(payload: RegisterRequest):
    # Uniqueness checks
    if db["user"].find_one({"email": payload.email}):
        raise HTTPException(status_code=400, detail="Email already in use")
    if db["user"].find_one({"username": payload.username}):
        raise HTTPException(status_code=400, detail="Username already in use")

    user_doc = {
        "username": payload.username,
        "email": payload.email,
        "password_hash": hash_password(payload.password),
        "avatar_url": None,
        "bio": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "subscriber_count": 0,
    }
    inserted_id = db["user"].insert_one(user_doc).inserted_id
    user_doc["_id"] = inserted_id
    user_doc.pop("password_hash", None)
    return to_str_id(user_doc)


@app.post("/auth/login")
def login(payload: LoginRequest):
    user = db["user"].find_one({"email": payload.email})
    if not user:
        raise HTTPException(status_code=400, detail="Invalid credentials")
    if not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Invalid credentials")
    # MVP: return user info; frontend will store user id and send with requests
    user.pop("password_hash", None)
    return to_str_id(user)


# Dependency to get current user id from header (MVP)
from fastapi import Header

def get_current_user_id(x_user_id: Optional[str] = Header(default=None, convert_underscores=False)) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")
    # Validate exists
    if not db["user"].find_one({"_id": objid(x_user_id)}):
        raise HTTPException(status_code=401, detail="Invalid user id")
    return x_user_id


# -------------------- Video Upload & Feed --------------------
@app.post("/videos")
async def upload_video(
    title: str = Form(...),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),  # comma separated
    file: UploadFile = File(...),
    thumbnail: Optional[UploadFile] = File(None),
    user_id: str = Depends(get_current_user_id),
):
    # Save video file
    ext = os.path.splitext(file.filename)[1] or ".mp4"
    video_filename = f"{ObjectId()}{ext}"
    video_path = os.path.join(VIDEO_DIR, video_filename)
    with open(video_path, "wb") as f:
        f.write(await file.read())
    video_url = f"/static/videos/{video_filename}"

    thumb_url = None
    if thumbnail is not None:
        t_ext = os.path.splitext(thumbnail.filename)[1] or ".jpg"
        thumb_filename = f"{ObjectId()}{t_ext}"
        thumb_path = os.path.join(THUMB_DIR, thumb_filename)
        with open(thumb_path, "wb") as tf:
            tf.write(await thumbnail.read())
        thumb_url = f"/static/thumbnails/{thumb_filename}"

    # Parse tags
    tag_list: List[str] = []
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    video_doc = {
        "user_id": user_id,
        "title": title,
        "description": description,
        "tags": tag_list,
        "video_url": video_url,
        "thumbnail_url": thumb_url,
        "views_count": 0,
        "likes_count": 0,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    vid = db["video"].insert_one(video_doc).inserted_id
    video_doc["_id"] = vid
    return to_str_id(video_doc)


@app.get("/videos")
def list_videos(limit: int = 20):
    cursor = db["video"].find({}).sort("created_at", -1).limit(limit)
    videos = [to_str_id(v) for v in cursor]
    return videos


@app.get("/videos/{video_id}")
def get_video(video_id: str):
    v = db["video"].find_one({"_id": objid(video_id)})
    if not v:
        raise HTTPException(status_code=404, detail="Video not found")
    # increment views
    db["video"].update_one({"_id": v["_id"]}, {"$inc": {"views_count": 1}, "$set": {"updated_at": datetime.utcnow()}})
    v = db["video"].find_one({"_id": v["_id"]})
    # include channel info
    user = db["user"].find_one({"_id": objid(v["user_id"])}) if v.get("user_id") else None
    payload = to_str_id(v)
    payload["channel"] = to_str_id(user) if user else None
    return payload


# -------------------- Comments --------------------
class CommentRequest(BaseModel):
    text: str


@app.post("/videos/{video_id}/comments")
def add_comment(video_id: str, payload: CommentRequest, user_id: str = Depends(get_current_user_id)):
    if not db["video"].find_one({"_id": objid(video_id)}):
        raise HTTPException(status_code=404, detail="Video not found")
    comment_doc = {
        "video_id": video_id,
        "user_id": user_id,
        "text": payload.text,
        "created_at": datetime.utcnow(),
    }
    cid = db["comment"].insert_one(comment_doc).inserted_id
    comment_doc["_id"] = cid
    return to_str_id(comment_doc)


@app.get("/videos/{video_id}/comments")
def list_comments(video_id: str, limit: int = 50):
    cursor = db["comment"].find({"video_id": video_id}).sort("created_at", -1).limit(limit)
    comments = []
    for c in cursor:
        user = db["user"].find_one({"_id": objid(c["user_id"])}) if c.get("user_id") else None
        item = to_str_id(c)
        item["user"] = to_str_id(user) if user else None
        comments.append(item)
    return comments


# -------------------- Likes --------------------
class LikeRequest(BaseModel):
    value: int = 1  # 1 like; -1 dislike (future)


@app.post("/videos/{video_id}/like")
def like_video(video_id: str, payload: LikeRequest, user_id: str = Depends(get_current_user_id)):
    if not db["video"].find_one({"_id": objid(video_id)}):
        raise HTTPException(status_code=404, detail="Video not found")
    existing = db["like"].find_one({"video_id": video_id, "user_id": user_id})
    if existing:
        # toggle/remove if same, else update
        if existing.get("value", 1) == payload.value:
            db["like"].delete_one({"_id": existing["_id"]})
        else:
            db["like"].update_one({"_id": existing["_id"]}, {"$set": {"value": payload.value}})
    else:
        db["like"].insert_one({"video_id": video_id, "user_id": user_id, "value": payload.value, "created_at": datetime.utcnow()})
    # recompute likes_count
    likes_count = db["like"].count_documents({"video_id": video_id, "value": 1})
    db["video"].update_one({"_id": objid(video_id)}, {"$set": {"likes_count": likes_count}})
    return {"video_id": video_id, "likes_count": likes_count}


# -------------------- Subscriptions & Channel --------------------
@app.post("/channels/{channel_id}/subscribe")
def subscribe_channel(channel_id: str, user_id: str = Depends(get_current_user_id)):
    if channel_id == user_id:
        raise HTTPException(status_code=400, detail="Cannot subscribe to yourself")
    if not db["user"].find_one({"_id": objid(channel_id)}):
        raise HTTPException(status_code=404, detail="Channel not found")
    existing = db["subscription"].find_one({"channel_id": channel_id, "subscriber_id": user_id})
    if existing:
        # toggle unsubscribe
        db["subscription"].delete_one({"_id": existing["_id"]})
    else:
        db["subscription"].insert_one({"channel_id": channel_id, "subscriber_id": user_id, "created_at": datetime.utcnow()})
    sub_count = db["subscription"].count_documents({"channel_id": channel_id})
    db["user"].update_one({"_id": objid(channel_id)}, {"$set": {"subscriber_count": sub_count}})
    return {"channel_id": channel_id, "subscriber_count": sub_count}


@app.get("/channels/{channel_id}")
def get_channel(channel_id: str):
    user = db["user"].find_one({"_id": objid(channel_id)})
    if not user:
        raise HTTPException(status_code=404, detail="Channel not found")
    sub_count = db["subscription"].count_documents({"channel_id": channel_id})
    videos = [to_str_id(v) for v in db["video"].find({"user_id": channel_id}).sort("created_at", -1)]
    payload = to_str_id(user)
    payload["subscriber_count"] = sub_count
    payload["videos"] = videos
    return payload


# -------------------- Simple Search/Feed --------------------
@app.get("/feed")
def feed(limit: int = 20):
    # Trending = most recent for MVP
    videos = [to_str_id(v) for v in db["video"].find({}).sort("created_at", -1).limit(limit)]
    return videos


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
