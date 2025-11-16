import os
from datetime import date, datetime, timedelta
from typing import List, Optional, Literal, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import create_document, get_documents, db

app = FastAPI(title="Smart Trippy API", description="Free AI-powered travel planning backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------
# Models / Schemas
# ----------------------
class ItineraryItem(BaseModel):
    day: int = Field(..., ge=1)
    type: Literal["hotel", "activity", "restaurant", "transport", "tip"]
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = "USD"
    link: Optional[str] = None
    available: bool = True
    vendor: Optional[str] = None


class PlanRequest(BaseModel):
    destination: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    travelers: int = 1
    preferences: Optional[str] = None
    budget: Optional[str] = None
    style: Optional[str] = None


class PlanResponse(BaseModel):
    destination: str
    start_date: date
    end_date: date
    nights: int
    travelers: int
    summary: str
    items: List[ItineraryItem]
    sources: List[Dict[str, str]]


class TripSaveRequest(BaseModel):
    name: str
    plan: PlanResponse


# ----------------------
# Utility: mock availability aggregator
# ----------------------
VENDORS = [
    ("Booking.com", "https://www.booking.com"),
    ("Airbnb", "https://www.airbnb.com"),
    ("Hotels.com", "https://www.hotels.com"),
    ("Expedia", "https://www.expedia.com"),
    ("Viator", "https://www.viator.com"),
    ("GetYourGuide", "https://www.getyourguide.com"),
]


def _mock_link(vendor_base: str, q: str) -> str:
    return f"{vendor_base}/search?q={q.replace(' ', '+')}"


def _generate_mock_plan(payload: PlanRequest) -> PlanResponse:
    today = date.today()
    start = payload.start_date or (today + timedelta(days=14))
    end = payload.end_date or (start + timedelta(days=4))
    nights = (end - start).days
    if nights <= 0:
        end = start + timedelta(days=4)
        nights = (end - start).days

    items: List[ItineraryItem] = []

    # Hotels (only bookable)
    for i in range(2):
        vendor_name, base = VENDORS[i % len(VENDORS)]
        hotel_name = f"{payload.destination} Boutique Hotel {i+1}"
        items.append(
            ItineraryItem(
                day=1,
                type="hotel",
                title=hotel_name,
                description=f"Centrally located stay for {nights} nights.",
                location=payload.destination,
                price=145 + i * 35,
                currency="USD",
                link=_mock_link(base, hotel_name),
                available=True,
                vendor=vendor_name,
            )
        )

    # Activities for each day
    for d in range(1, nights + 1):
        vendor_name, base = VENDORS[(d + 2) % len(VENDORS)]
        act_title = f"Guided walking tour - Day {d}"
        items.append(
            ItineraryItem(
                day=d,
                type="activity",
                title=act_title,
                description="Highly rated experience with instant confirmation.",
                location=payload.destination,
                price=39.0,
                currency="USD",
                link=_mock_link(base, f"{payload.destination} walking tour"),
                available=True,
                vendor=vendor_name,
                start_time="10:00",
                end_time="12:00",
            )
        )
        rest_title = f"Cozy local restaurant - Day {d}"
        items.append(
            ItineraryItem(
                day=d,
                type="restaurant",
                title=rest_title,
                description="Loved by locals. Reserve a table online.",
                location=payload.destination,
                price=None,
                link=_mock_link("https://www.opentable.com", f"{payload.destination} dinner"),
                available=True,
                vendor="OpenTable",
                start_time="19:30",
            )
        )

    sources = [
        {"name": "Tripadvisor", "url": "https://www.tripadvisor.com"},
        {"name": "Viator", "url": "https://www.viator.com"},
    ]

    summary = (
        f"Personalized {nights}-night plan for {payload.destination}. "
        f"Optimized for {payload.travelers} traveler(s)"
        + (f" with a {payload.style} vibe" if payload.style else "")
        + (f" and {payload.budget} budget." if payload.budget else ".")
    )

    return PlanResponse(
        destination=payload.destination,
        start_date=start,
        end_date=end,
        nights=nights,
        travelers=payload.travelers,
        summary=summary,
        items=items,
        sources=sources,
    )


# ----------------------
# Routes
# ----------------------
@app.get("/")
def read_root():
    return {"message": "Smart Trippy Backend is running"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from Smart Trippy API"}


@app.post("/api/plan", response_model=PlanResponse)
def plan_trip(payload: PlanRequest):
    if not payload.destination:
        raise HTTPException(status_code=400, detail="Destination is required")
    plan = _generate_mock_plan(payload)
    return plan


@app.post("/api/trips")
def save_trip(req: TripSaveRequest):
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    doc = {
        "name": req.name,
        "plan": req.plan.model_dump(),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    inserted_id = create_document("trip", doc)
    return {"id": inserted_id, "status": "saved"}


@app.get("/api/trips")
def list_trips(limit: int = 20):
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    docs = get_documents("trip", limit=limit)
    # Convert ObjectId to str if present
    sanitized: List[Dict[str, Any]] = []
    for d in docs:
        d["_id"] = str(d.get("_id"))
        sanitized.append(d)
    return {"trips": sanitized}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = getattr(db, "name", None)
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
