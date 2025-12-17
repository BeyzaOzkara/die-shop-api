from sqlalchemy.orm import Session
from .models import ProductionOrder, Die  # zaten importlu

def generate_production_order_number(db: Session, die: Die) -> str:
    """
    UE-<KALIP_NO>-001, UE-<KALIP_NO>-002 ...
    """
    base = f"UE-{die.die_number}"  # örn: UE-1100-1

    last = (
        db.query(ProductionOrder.order_number)
        .filter(
            ProductionOrder.die_id == die.id,
            ProductionOrder.order_number.like(f"{base}-%"),
        )
        .order_by(ProductionOrder.order_number.desc())
        .first()
    )

    if last:
        last_number = last[0]  # ('UE-1100-1-003',)
        parts = last_number.split("-")
        try:
            seq = int(parts[-1]) + 1
        except ValueError:
            seq = 1
    else:
        seq = 1

    return f"{base}-{seq:03d}"  # UE-1100-1-001

def generate_work_order_number(die: Die, po: ProductionOrder, index: int) -> str:
    """
    Üretim emri: UE-<DIE_NO>-003
    İş emri:     IE-<DIE_NO>-003-01, IE-<DIE_NO>-003-02 ...
    """
    parts = po.order_number.split("-", 2)  # ['UE', '<DIE_NO>', '003'] bekliyoruz
    if len(parts) == 3:
        _, die_number, po_seq = parts
    else:
        die_number = die.die_number
        po_seq = "001"
    return f"IE-{die_number}-{po_seq}-{index:02d}"
