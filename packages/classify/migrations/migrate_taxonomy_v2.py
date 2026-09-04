"""One-off migration: category taxonomy v2 (17 categories, down from 20).

See docs/superpowers/specs/2026-09-04-category-taxonomy-v2-design.md for
the full rationale and per-rule verification notes. This module is data +
pure functions only — no I/O, no Store writes. See migrate() at the
bottom of this file (added in Task 3) for the apply/dry-run entry points,
and __main__ (Task 4) for the CLI wrapper.
"""

# ---------------------------------------------------------------- taxonomy
NEW_CATEGORIES = [
    "Groceries", "Dining", "Transport", "Shopping", "Subscriptions",
    "Utilities", "Housing", "Health", "Entertainment", "Travel",
    "Education", "Income", "Investments", "Transfers", "Family & Friends",
    "Other", "Cash",
]

NEW_CATEGORY_TREE = {
    "Groceries": "Expenses:Groceries",
    "Dining": "Expenses:Dining",
    "Transport": "Expenses:Transport",
    "Shopping": "Expenses:Shopping",
    "Subscriptions": "Expenses:Subscriptions",
    "Utilities": "Expenses:Utilities",
    "Housing": "Expenses:Housing",
    "Health": "Expenses:Health",
    "Entertainment": "Expenses:Entertainment",
    "Travel": "Expenses:Travel",
    "Education": "Expenses:Education",
    "Income": "Income",
    "Investments": "Assets:Investments",
    "Transfers": "Equity:Transfers",
    "Family & Friends": "Expenses:Family & Friends",
    "Other": "Expenses:Other",
    "Cash": "Expenses:Cash",
}

NEW_SUBCATEGORIES = {
    "Groceries": ["Meat", "Alcohol", "Produce"],
    "Dining": ["Delivery", "Dining Out"],
    "Transport": ["Fuel", "Cabs/Rideshare", "Public Transit", "Parking"],
    "Subscriptions": ["Business Tools", "Personal"],
    "Utilities": ["Electricity", "Gas", "Telecom/Internet"],
    "Housing": ["Rent", "Maintenance/Dues", "Property Tax", "Repairs",
                "Household Help"],
    "Health": ["Insurance", "Care"],
    "Travel": ["Flights", "Hotels/Packages", "Forex/Prepaid Cards"],
    "Investments": ["FD/Deposits", "Mutual Funds", "Crypto", "Chit/Kuri"],
    "Transfers": ["Credit Card Payment"],
    "Family & Friends": ["Gifts/Support", "Loans"],
}

# ----------------------------------------------------- whole-category moves
# Every transaction/memory-row currently in one of these categories moves
# to the paired (new_category, new_subcategory) regardless of merchant.
WHOLE_CATEGORY_MOVES = {
    "Fuel": ("Transport", "Fuel"),
    "Rent": ("Housing", "Rent"),
    "Household Help": ("Housing", "Household Help"),
    "Fees & Charges": ("Other", ""),
}

# ------------------------------------------------------------ CRED Club fix
# Verified via raw UPI narration: each of these routes through the
# cred.club@... VPA (the credit-card-bill-pay feature specifically), not
# cred.utility@... or credpay.<biller>@... (CRED's other bill-pay
# integrations, which stay wherever they already are — see the design
# spec's Rule 4 "explicitly excluded" list).
CRED_PATTERNS = [
    "AXIS CRED CLUB",
    "CRED CRED CLUB",
    "CREDCLUB1 CRED CLUB",
    "HI2PVCTTXO1SC8 RAZPCREDCLUB",
    "HVKZDKG4QCYSHU RAZPCREDCLUB",
    "KQSHY4UOARZKHPOSD4 PAYUCREDCLUB",
    "UPI AXIS CRED CLUB AXISB UTIB0000114 PAYM ENT ON CRED",
]

# --------------------------------------------------------- Utilities split
# 100 distinct merchant patterns from the live Utilities category, audited
# by keyword and spot-checked against raw narration. UTILITIES_STAYS lists
# the patterns that need NO change (kept here only so Task 1's coverage
# test can assert all 100 patterns are accounted for; not used to build
# PATTERN_MOVES).
UTILITIES_HOUSING_DUES = [
    "AISSHWARYA EXCELLENC AEAOA",
    "AISSHWARYA EXCELLENC AEAOA084 08",
    "AISSHWARYA EXCELLENC AEAOA1",
    "EMI MYGATEBANGALORE",
    "MY GATE NOIDA",
    "MY GATENOIDA",
    "MYGATE",
    "MYGATE MYGATE RAZORPAY",
    "MYGATE MYGATE RZP",
    "MYGATE PAYTM MYGATE",
    "MYGATEBANGALORE",
    "SATTVA GOLD SUMMIT A SATTVAGOLDSUMMITAPARTMENTASSOCIATION",
    "SATTVA GOLD SUMMIT A SGSAOA",
    "UPI MYGATE MYGATE RAZORPAY HDFCBANK HDFC0000053 DUESSETTLE VALUE DT 09 07 2024",
    "UPI MYGATE MYGATE RAZORPAY HDFCBANK HDFC0000053 DUESSETTLE VALUE DT 13 08 2024",
    "UPI MYGATE PAYTM MYGATE PAYTM YESB0PTMUPI UTIL ITY VALUE DT 19 03 2024",
    "UPI VIVISH MYGATE PAYTM HDFCBANK HDFC0MERUPI U PI VALUE DT 06 02 2026",
    "UPI VIVISH MYGATE PAYTM HDFCBANK HDFC0MERUPI U PI VALUE DT 16 03 2026",
    "UPI XXXXXX7770 SBIN0008627 SGS PENDING",
    "VIVISH MYGATE PAYTM",
]

UTILITIES_HOUSING_TAX = [
    "COMMISSIONER BBMP",
    "UPI TONY PIUS ALAPATT TONYPIUSALAPATT OKSBI SIBL0000396 BBMP VALUE DT 12 11 2025",
    "UPI XXXXXXXXXXX1736 UBIN0900745 53 BBMP BESCOM NAME C VALUE DT 15 11 2025",
    "UPI XXXXXXXXXXX1736 UBIN0900745 KHATA BESCOM",
]

UTILITIES_HOUSING_REPAIRS = [
    "BUHARI K K TAJELECTRICALS",
    "PRADEEP HARDWARE AND EL",
    "UPI ARUMUGAM KANNAPATTU PAYTMQR72KASC PTYS YESB0PTMUPI TOILET VALUE DT 03 07 2026",
    "UPI GOUTAM MALIK 2 YBL PUNB0101220 PLUMBER TOILET REP VALUE DT 18 03 2026",
    "UPI GOUTAM MALIK 2 YBL PUNB0101220 PLUMBER WORKS VALUE DT 24 03 2026",
    "UPI GOUTAM MALIK GUDUMALIK915 YBL ICIC0001422 PLUMBER VALUE DT 26 05 2026",
    "UPI JITENDRA KUMAR M PAYTMQRMEUVDHTUDA PAYTM PYTM0123456 ELE CTRICAL VALUE DT 10 12 2023",
    "UPI PRADEEP HARDWARE AND OKBIZAXIS UTIB0000000 B ULBSVALUE DT 01 03 2024",
    "UPI RADHANATH KAR RADHANATH158 OKAXIS SBIN0009820 PLUMB ER VALUE DT 25 05 2026",
    "UPI RADHANATH158OKAXIS RADHANATH158 OKAXIS SBIN0009820 PLUMB ER VALUE DT 02 07 2026",
    "UPI RADHANATH158OKAXIS RADHANATH158 OKAXIS SBIN0009820 PLUMBI NGWORK VALUE DT 04 06 2026",
    "UPI RAJALAKSHMI HARDWARE PAYTMQR6VAZ3Q PTYS YESB0PTMUPI PLUMBI NG VALUE DT 03 07 2026",
    "URBANCLAP NOIDA",
]

UTILITIES_HOUSING_HELP = [
    "NIJARA DAS BAISHYSNIJARA",
    "UPI CHANDRIKA MARY CHANDRIKACHANDRIKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 04 04 2026",
    "UPI CHANDRIKA MARY CHANDRIKACHANDRIKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 07 01 2026",
    "UPI CHANDRIKA MARY CHANDRIKACHANDRIKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 11 02 2026",
    "UPI CHANDRIKA MARY CHANDRIKACHANDRIKA939 OKAXIS SBIN0017734 COOK VALUE DT 07 05 2026",
    "UPI CHANDRIKACHANDRIKA93 CHANDRIKACHANDR IKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 04 03 2026",
    "UPI CHANDRIKACHANDRIKA93 CHANDRIKACHANDR IKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 08 12 2025",
    "UPI CHANDRIKACHANDRIKA93 CHANDRIKACHANDR IKA939 OKAXIS SBIN0017734 COOK SALARY VALUE DT 22 07 2026",
    "UPI NIJARA DAS DNIJARA82 OKAXIS IOBA0003395 SALARY PENDING VALUE DT 29 03 2026",
]

UTILITIES_HOUSING_MISC = [
    "REV UPI TONYPIUSALAPA TT OKHDFCBANK HOUSE MISCELLANEOUS VALUE DT 28 02 2024",
    "RURAL DEVELOPMENT AND",
]

UTILITIES_TO_OTHER = [
    "7259838127PTYES",
    "9871094364PTYES",
    "AKSHAY KUMAR TT AKSHAYSANTHOSHTT",
    "BABRUBAHAN PARIDA BABULPARIDA2020",
    "BABU BABUBABU84419",
    "BAIKUNTH DAS DASBAIKUNTHA65",
    "CREATELINE MAHALAXMI",
    "DINESH SETTU DINESH2000123456",
    "DOMINIC J JDOMINIC9980854213",
    "GARIKINA RATNAM KIRANSAFETYNET",
    "HASEENA V A",
    "K SHAMALA BABUG4571",
    "KHAN ALFITKHAN MANGL",
    "KUMARAVEL ALAGESAN KUMARAVELGK1982",
    "L M SHIVU SHIVUM15021993",
    "MANOJCTLOKICICI MANOJCTL",
    "RATHEESH K V PAYTMQR1RXCQHWGB3",
    "SHANAVAZ P S SHANAVASSHANU78639",
    "VEDANAYAGAM K VEDANAYAGAMVEDANAYAGAM67",
]

UTILITIES_TO_TRANSPORT = [
    "BANGALORE TRAFFIC POLI",
]

UTILITIES_STAYS = [
    "AIRTEL BAN GURGAON",
    "AIRTEL GURGAON",
    "AIRTEL66 GURGAON",
    "ASIANET",
    "BESCOM BILLDESK",
    "BESCOMBANGALORE",
    "BESCOMMUMBAI",
    "BHARTI AIRTEL GURGAON",
    "BHARTI AIRTEL LTDGURGAON",
    "BSNL BILLDESK",
    "CRED CRED UTILITY",
    "EMI BESCOMMUMBAI",
    "EURONETGPAY EURONETGPAY POSTP AID MOBILE",
    "GAIL GAS LIMITEDNOIDA",
    "JIO POSTPAID BILL PA PAYTM",
    "JIO PREPAID RECHARGE PAYTM JIOMOBILITY",
    "JIO SOLUTIONS HTTPS WW",
    "KSEB TRIVANDRUM",
    "RAZ AIRWIRE BROADBAND",
    "RAZ NORTHEAST DATAA NE HTTPS AI",
    "RAZ VODAFONE IDEA LIMIT GANDHINAGA",
    "RECHARGE",
    "RECHARGEMUMBAI",
    "REL JIO SOLUTI HTTPS WW",
    "RELIANCE JIO INFOCOMM LNOIDA",
    "RELIANCE JIO INFOCOMM NOIDA",
    "UPI JIO CREDPAY JIO AXISB UTIB0000114 PAYM ENT ON CRED",
    "UPI MAMALYTICS TECHNOLOG SSEOMNI1H8F7A060125POS MAIRTEL AIRP0000001 PAYM ENTTOAARAM VALUE DT 07 12 2025",
    "VI VILPOSKAR",
    "VODAFONE IDEA GANDHINAGA",
    "WALLET NOIDA",
    "WWW AIRTEL INGURGAON",
]


def build_pattern_moves() -> dict[str, tuple[str, str]]:
    """Assemble the full pattern -> (new_category, new_subcategory) table
    from CRED_PATTERNS plus every Utilities-split bucket except
    UTILITIES_STAYS (those need no move)."""
    moves: dict[str, tuple[str, str]] = {}
    for p in CRED_PATTERNS:
        moves[p] = ("Transfers", "Credit Card Payment")
    for p in UTILITIES_HOUSING_DUES:
        moves[p] = ("Housing", "Maintenance/Dues")
    for p in UTILITIES_HOUSING_TAX:
        moves[p] = ("Housing", "Property Tax")
    for p in UTILITIES_HOUSING_REPAIRS:
        moves[p] = ("Housing", "Repairs")
    for p in UTILITIES_HOUSING_HELP:
        moves[p] = ("Housing", "Household Help")
    for p in UTILITIES_HOUSING_MISC:
        moves[p] = ("Housing", "")
    for p in UTILITIES_TO_OTHER:
        moves[p] = ("Other", "")
    for p in UTILITIES_TO_TRANSPORT:
        moves[p] = ("Transport", "")
    return moves


PATTERN_MOVES = build_pattern_moves()
