# Save this file as main.py
import uuid
import hmac
import hashlib
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Depends, Request, Header

app = FastAPI(title="Universal Escrow & Marketplace Engine", version="1.0.0")

# --- SIMULATED IN-MEMORY DATABASE (Replace with SQLAlchemy / PostgreSQL in production) ---
USERS_DB = {}
ESCROW_TRANSACTIONS = {}
PAYSTACK_SECRET_KEY = "sk_test_mock_key_for_security_validation"

# --- PYDANTIC SCHEMAS ---
class UserOnboarding(BaseModel):
    user_id: str
    email: str
    is_seller: bool

class EscrowLinkRequest(BaseModel):
    seller_id: str
    buyer_id: Optional[str] = None  # Optional if generated as an open public link (e.g., for Jiji)
    amount: float = Field(..., gt=100, description="Transaction amount in Naira")
    item_description: str
    source_platform: str = "Internal"  # Can be "Jiji", "Freelance Market", "Twitter", etc.

class UpdateStatusRequest(BaseModel):
    updated_by: str  # "seller" or "buyer"
    status_action: str  # "sent" or "received"

# --- HELPER FUNCTIONS: FEE CALCULATORS ---
def calculate_escrow_fee(amount: float) -> float:
    """Applies a 3% escrow fee capped strictly at 5,000 Naira"""
    fee = amount * 0.03
    return min(fee, 5000.0)

# --- ENDPOINT 1: USER ONBOARDING & ONE-TIME SELLER FEE TRACKER ---
@app.post("/api/users/onboard", tags=["User Management"])
async def onboard_user(user: UserOnboarding):
    if user.user_id in USERS_DB:
        return {"status": "exists", "message": "User already registered", "data": USERS_DB[user.user_id]}
    
    USERS_DB[user.user_id] = {
        "email": user.email,
        "is_seller": user.is_seller,
        "has_made_first_sale": False,
        "one_time_fee_charged": False
    }
    return {"status": "success", "message": "User profile initialized", "data": USERS_DB[user.user_id]}

# --- ENDPOINT 2: UNIVERSAL DECOUPLED ESCROW LINK GENERATOR ---
@app.post("/api/escrow/generate-link", tags=["Escrow Core"])
async def generate_universal_escrow_link(request: EscrowLinkRequest):
    transaction_id = str(uuid.uuid4())
    escrow_fee = calculate_escrow_fee(request.amount)
    total_buyer_payable = request.amount + escrow_fee
    
    # Structure transaction token payload
    transaction_payload = {
        "transaction_id": transaction_id,
        "seller_id": request.seller_id,
        "buyer_id": request.buyer_id,
        "amount": request.amount,
        "escrow_fee": escrow_fee,
        "total_buyer_payable": total_buyer_payable,
        "item_description": request.item_description,
        "source_platform": request.source_platform,
        "payment_status": "pending",
        "shipping_status": "not_sent",
        "buyer_confirmation": "pending",
        "dispute_status": "none",
        "universal_url": f"https://your-escrow-app.com{transaction_id}"
    }
    
    ESCROW_TRANSACTIONS[transaction_id] = transaction_payload
    return {
        "status": "success",
        "message": f"Universal escrow link generated for {request.source_platform}",
        "transaction_id": transaction_id,
        "shareable_url": transaction_payload["universal_url"],
        "fee_breakdown": {"base": request.amount, "fee": escrow_fee, "total": total_buyer_payable}
    }

# --- ENDPOINT 3: SELLER/BUYER DOUBLE-TICK ONSCREEN MANUAL STATUS UPDATE ---
@app.patch("/api/escrow/{transaction_id}/update-status", tags=["Escrow Core"])
async def update_transaction_status(transaction_id: str, request: UpdateStatusRequest):
    if transaction_id not in ESCROW_TRANSACTIONS:
        raise HTTPException(status_code=404, detail="Transaction token not found")
    
    tx = ESCROW_TRANSACTIONS[transaction_id]
    
    if request.updated_by == "seller" and request.status_action == "sent":
        tx["shipping_status"] = "dispatched"
    elif request.updated_by == "buyer" and request.status_action == "received":
        tx["buyer_confirmation"] = "confirmed"
        # If buyer confirms, trigger settlement protocol instantly
        return await execute_payout_settlement(transaction_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid status action mutation workflow")
        
    return {"status": "success", "message": "Transaction state updated", "data": tx}

# --- INTERNAL PROTOCOL: PAYSTACK DISBURSEMENT & SELLER ONE-TIME FEE COLLECTION ---
async def execute_payout_settlement(transaction_id: str):
    tx = ESCROW_TRANSACTIONS[transaction_id]
    seller_id = tx["seller_id"]
    seller_profile = USERS_DB.get(seller_id)
    
    payout_amount = tx["amount"]
    fee_deduction_notice = "Standard transaction payout processed."
    
    # Deduct one-time 500 NGN Seller Fee exclusively after their first completed sale
    if seller_profile and not seller_profile["has_made_first_sale"]:
        payout_amount -= 500.0
        seller_profile["has_made_first_sale"] = True
        seller_profile["one_time_fee_charged"] = True
        fee_deduction_notice = "First sale detected. 500 NGN one-time configuration fee applied."
        
    tx["payment_status"] = "settled_to_seller"
    
    return {
        "status": "success",
        "message": "Funds released from escrow ledger successfully via Paystack Subaccount API",
        "net_payout_to_seller": payout_amount,
        "system_audit": fee_deduction_notice
    }

# --- ENDPOINT 4: AUTOMATED LOGISTICS WEBHOOK INTERCEPTOR (TRACKING API) ---
@app.post("/api/webhooks/logistics-tracker", tags=["Automated Logistics"])
async def logistics_provider_webhook(payload: dict, x_logistics_signature: str = Header(None)):
    """Receives automated delivery updates from tracking partners (e.g., GIGL, DHL, Terminal Africa)"""
    tracking_id = payload.get("tracking_id")
    current_delivery_event = payload.get("status")  # e.g., "DELIVERED"
    associated_tx_id = payload.get("metadata", {}).get("transaction_id")
    
    if associated_tx_id in ESCROW_TRANSACTIONS:
        tx = ESCROW_TRANSACTIONS[associated_tx_id]
        if current_delivery_event == "DELIVERED":
            tx["shipping_status"] = "arrived_at_destination"
            # Flag system that shipping is verified; system prompts buyer or starts auto-release countdown
            return {"status": "processed", "action": "Verification flag attached. Waiting for settlement window."}
            
    return {"status": "ignored", "message": "No matching active escrow pipeline found"}

# --- ENDPOINT 5: DISPUTE HANDLING & AI TEXT SCREENING SYSTEM ---
@app.post("/api/escrow/{transaction_id}/raise-dispute", tags=["Dispute Resolution & AI"])
async def initiate_dispute_resolution(transaction_id: str, buyer_complaint: str, evidence_urls: list[str]):
    if transaction_id not in ESCROW_TRANSACTIONS:
        raise HTTPException(status_code=404, detail="Transaction token not found")
        
    tx = ESCROW_TRANSACTIONS[transaction_id]
    tx["dispute_status"] = "under_review"
    
    # Mock Processing Engine for AI Analysis Simulation
    ai_risk_score = len(buyer_complaint) % 100  # Stand-in calculation logic mimicking classification confidence
    ai_recommendation = "Escalate to Human Arbitrator" if ai_risk_score > 50 else "Approve Auto-Refund Protocol"
    
    return {
        "status": "dispute_opened",
        "transaction_details": tx,
        "ai_dispute_screening": {
            "risk_index_score": f"{ai_risk_score}%",
            "detected_sentiment": "High Friction Conflict Alert",
            "automated_ai_recommendation": ai_recommendation,
            "next_action": "Tracking telemetry logs queued for administrative audit comparison"
        }
    }
