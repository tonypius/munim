"""One-off migration: subcategory classification pass v1.

See docs/superpowers/specs/2026-09-04-subcategory-classification-v1-design.md
for the full rationale, per-bucket verification notes, and the two
things this script does NOT do the way a pattern-move table would
suggest: the Health Care default (applied to every remaining Health
transaction, not a pattern list) and the Melvin loan fix (two
transaction ids, not a merchant pattern — see apply_migration in a
later task).
"""

# ------------------------------------------------------- Groceries: Meat
GROCERIES_MEAT = [
    "FRESHTOHOME FOODS PRIVA",
    "RAZ FRESHTOHOME FOODS HTTPS WW",
    "FRESHTOHOME INR",
    "FRESHTOHOME",
    "EMI FRESHTOHOME FOODS PRIVA",
    "FRESHTOHOME FOODS PRIV HTTPS WW",
    "FRESHTOHOME FOODS PRIV",
    "FRESHTOHOMEBANGALORE",
    "RAZ FRESHTOHOME MOHALI",
    "UPI FRESHTOHOME FRESHTOHOME ESBZ MAIRTEL AIRP0000001 PAY VALUE DT 15 04 2026",
    "MY CHICKEN AND MORE",
    "5 STAR MEAT PAYTMQR61EFA6",
    "PICKET FENCE FARMS E PICKETFENCEFARMS",
]

# ---------------------------------------------------- Groceries: Alcohol
GROCERIES_ALCOHOL = [
    "KERALA STATE BEVERAGES THRISSUR",
    "KERALA STATE BEVERAGES TRICHUR",
    "S S LIQUORS",
    "LIVING LIQUIDZ",
    "TONIQUE BEVERAGES",
    "TONIQUE",
    "MR SPIRITS LLP",
    "EMI KERALA STATE BEVERAGESCOTHRISSUR",
    "AR LIQUORS A UNIT OF A",
    "KERALA STATE BEVERAGESCOTHRISSUR",
    "AR LIQUORS A UNIT OF ARBANGALORE",
    "TONIQUEBANGALORE",
    "LIQUOR ZONEBENGALURU",
    "KERALA STATE BEVERAGESERNAKULAM",
    "KERALA STATE BEVERAGES COTHRISSUR",
]

# ---------------------------------------------------- Groceries: Produce
GROCERIES_PRODUCE = [
    "UPI K V R VEGETABLES VYAPAR 175208945306HDFCB ANK HDFC0MERUPI VEGETA BLE",
    "LULU S VEGETABLES SH PAYTMQR281005050101F2X0K15ZHZEQ",
]

# --------------------------------------------------------- Health: Insurance
HEALTH_INSURANCE = [
    "STAR HEALTH AND ALLIED CHENNAI",
    "STAR HEALTH AND ALLI STARHEALTH INSURANCE",
    "POLICYBAZAAR COM GURGAON",
    "EMI STAR HEALTH AND ALLIEDCHENNAI",
    "UPI XXXXXX0900 INDB0000007 HEALTH INSURANCE",
]

HEALTH_CARE_DEFAULT_CATEGORY = "Health"
HEALTH_CARE_DEFAULT_SUBCATEGORY = "Care"

# ---------------------------------------------------------- Dining: Delivery
DINING_DELIVERY = [
    "CRED SWIGGY",
    "EMI RAZ SWIGGYBENGALURU",
    "EMI SWIGGYBENGALURU",
    "EMI ZOMATO LIMITEDGURUGRAM",
    "PAY SWIGGYBANGALORE",
    "PAYTM ZOMATOLIMITED GURGAON",
    "RAZ SWIGGYBANGALORE",
    "RAZ ZOMATO HTTPS HY",
    "RAZ ZOMATO HYPERPURE HTTPS HY",
    "RAZ ZOMATO ONLINE ORDER GURGAON",
    "SWIGGY",
    "SWIGGY DASH",
    "SWIGGY E COMBANGALORE",
    "SWIGGY FOOD",
    "SWIGGY FOOD1BENGALURU",
    "SWIGGY FOODBANGALORE",
    "SWIGGY GENIE",
    "SWIGGY GO",
    "SWIGGY IN",
    "SWIGGY INBANGALORE",
    "SWIGGY LIMITEDBANGALORE",
    "SWIGGY LIMITEDBENGALURU",
    "SWIGGYBANGALORE",
    "SWIGGYBENGALURU",
    "UPI SWIGGY SWIGGY STORES AXB UTIB0000100 PAY FOR INTENT VALUE DT 03 04 2026",
    "UPI SWIGGY SWIGGYSTORES ICICI ICIC0DC0099 FOOD VALUE DT 04 02 2026",
    "WWW SWIGGY COM GURGAON",
    "WWW SWIGGY IN GURGAON",
    "WWW SWIGGY INBANGALORE",
    "ZOMATO",
    "ZOMATO COM GURGAON",
    "ZOMATO GURGAON",
    "ZOMATO GURUGRAM",
    "ZOMATO HTTPS WW",
    "ZOMATO HYPERPURGURGAON",
    "ZOMATO INTERNET PRIV WWW HYPERP",
    "ZOMATO MEDIA GURGAON",
    "ZOMATO MEDIA L GURGAON",
    "ZOMATO MEDIA L NOIDA",
    "ZOMATO MEDIA L WWW ZOMATO",
    "ZOMATO MEDIA LINOIDA",
    "ZOMATO MEDIA WWW ZOMATO",
    "ZOMATO NEW",
    "ZOMATO WWW ZOMATO",
    "ZOMATO ZOMATO ORDER",
    "ZOMATO ZOMATO1 GPAY",
    "ZOMATO ZOMATOORDER1 GPAY",
    "ZOMATONEW",
]

# --------------------------------------------------------- Dining: Dining Out
DINING_OUT = [
    "BREWSKY HENNUR BREWERY",
    "EMI DISTRICT DINING CYBSGURGAON",
    "EMI THE COMMISSIONERBLR EABANGALORE",
    "DISTRICT DINING CYBSGURGAON",
    "BOSCO EATERYBANGALORE",
    "BREWSKYBREWERYHENNUR",
    "AAVAKAY THE ANDHRA KITCMUMBAI",
    "THE RENAI COCHIN COCHIN",
    "EMI HOTEL SOUZA LOBONORTH GOA",
    "AAM VICTUALS LIMIMUMBAI",
    "BUFFALO WILD WINGS",
    "ANUPAMS COAST TO COAST",
    "BLABBER ALL DAY",
    "DISTRICT DINING CYBS GURGAON",
    "EMI DISTRICT DININGNEW",
    "BEER WORKS RESTAURANTS",
    "EMI HOTEL SHADABRANGA REDDY",
    "THE KINGS FIELD RESTAU",
    "DISTRICT DINING CYBSNEWDELHI",
    "DISTRICT DININGNEW",
    "DISTRICT DINING DISTRICTDINING PAYU",
]

# ----------------------------------------------- Transport: Fuel (additional)
TRANSPORT_FUEL_EXTRA = [
    "GOKULA SERVICE STATION",
    "PATEL SERVICE STATIONBANGALORE",
    "BHARAT PETROLEUM CORPOR DHARMAPURI",
    "SOUTHERN PETROLEUM ANGAMALLY",
    "PATEL SERVICE STATIONPBANGALORE",
    "AVARAN PETROLEUM IRINJALAKU",
    "MS NEW BOMBAY PETROLEUM THANE",
    "BHARAT PETROLEUM CORPOR",
    "HINDUSTAN PETROLEUM CORKRISHNAGIRI",
    "AVARAN PETROLEUMIRINJALAKU",
    "MAHIM SERVICE STATION",
    "HIGHWAY PETROLEUM ERNAKULAM",
]

# -------------------------------------------- Transport: Cabs/Rideshare
TRANSPORT_CABS = [
    "PAYTM UBERINDIASYSTE NOIDA",
    "UBER SYSTE NOIDA",
    "UBER SYSTEMS GURGAON",
    "UBER SYSTEMS P UBER",
    "UBER SYSTEMS P UBER1 RZP",
    "UBER SYSTEMS P UBERRIDES",
    "UBER SYSTEMS PRI HTTPS WW",
    "UBER SYSTEMS PRI NOIDA",
    "UBER SYSTEMS PRIV GURGAON",
    "UBER SYSTEMS PRIVNOIDA",
    "UBER TRIP HELP UBER COM LONDON",
    "UBERINDIASYSTEMSPRIVAT NOIDA",
    "UPI SREEJITH S IBL SBIN0070038 UBER TAXI VALUE DT 19 03 2026",
    "UPI UBER SYSTEMS P UBER AXISBANK UTIB0000000 C HARGEVALUE DT 08 03 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 CHARGEVALUE DT 02 02 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 CHARGEVALUE DT 04 03 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 CHARGEVALUE DT 08 03 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 UBERRIDE VALUE DT 04 03 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 UBERRIDE VALUE DT 23 03 2024",
    "UPI UBER SYSTEMS P UBERRIDES HDFCBANK HDFC0000499 UBERRIDE VALUE DT 25 01 2024",
]
# NOTE: 'THURUTHUMMEL ENERGY HUBERNAKULAM' matched a naive "UBER"
# substring search but is an energy company hub in Ernakulam
# ("...HUB-ERNAKULAM") -- deliberately excluded, not an oversight.

# ------------------------------------------- Transport: Public Transit
TRANSPORT_PUBLIC_TRANSIT = [
    "REDBUS",
    "IRCTC",
    "ROAD TRANSPORT CORPORATMUMBAI",
    "KARNATAKA STATE ROAD T GURGAON",
    "REDBUS BANGALORE",
    "IRCTC E TICKETING",
    "IRCTC NEW",
    "KARNATAKA STATE ROAD T",
    "RAZ IRCTC HTTPS WW",
    "REDBUS L",
    "EMI RAZ KARNATAKA STATE ROAD",
    "IRCTC AUTOPE GURGAON",
    "KERALA STATE ROAD TR KERALARTCONLINE",
    "KARNATAKA STATE ROAD KARNATAKASTATEROADTRANSPORTCORPORATION RZP",
]

# ------------------------------------------ Subscriptions: Business Tools
SUBSCRIPTIONS_BUSINESS_TOOLS = [
    "GOOGLE WORKSPACE CYBS SI",
    "DIGITALOCEAN COM AMSTERDAM",
    "DIGITALOCEAN COM DIGITALOCE",
    "PAYPAL DIGITALOCEA",
    "SLACK T63PG8P6H DUBLIN",
    "GOOGLE WORKSPACE CYBS SMUMBAI",
    "GODADDY DOMAIN",
    "GODADDY DOMAINS AMUMBAI",
    "GODADDY DOMAINS",
    "GOOGLE ADS",
    "GOOGLE WORKSPACE",
    "ADOBE ADOBE LY E",
    "DIGITALOCEAN COM GROSVENOR",
    "EMI ANTHROPIC CLAUDE TEAMANTHROPIC USD 225 00",
    "GOOGLE WORKSPACE CYBSSI",
    "EMI GOOGLE WORKSPACE CYBSSI",
    "EMI STRIPE Z AISINGAPORE USD 182 35",
    "GOOGLE ADWORDS",
    "OPENAI OPENAI COM",
    "DIGITALOCEAN COM AMSTERDAM USD 10 42",
    "DIGITALOCEAN COM AMSTERDAM USD 8 50",
    "ADOBE SOFTWARE WWW ADOBE",
    "ADOBE CREATIVE CLOUD ADOBE LY E",
    "WWW GODADDY COM PGSI WWW GODADD",
    "GOOGLE ADWORDS NAVI",
    "EMI STRIPE Z AISINGAPORE USD 84 37",
    "EMI STRIPE Z AISINGAPORE USD 81 00",
    "ANTHROPIC CLAUDE SUBANTHROPIC",
    "SLACK T63PG8P6H DUBLIN USD 74 17",
    "DIGITALOCEAN COMAMSTERDAM USD 9 92",
    "SLACK T63PG8P6H DUBLIN USD 73 39",
    "SLACK T63PG8P6H DUBLIN USD 70 79",
    "SLACK T63PG8P6H DUBLIN USD 69 30",
    "SLACK T63PG8P6H DUBLIN USD 66 73",
    "SLACK T63PG8P6H DUBLIN USD 64 13",
    "SLACK T63PG8P6H DUBLIN USD 65 68",
    "SLACK T63PG8P6H DUBLIN USD 65 49",
    "SLACK T63PG8P6H DUBLIN USD 62 10",
    "GOOGLE ADWORDS PGSI PLAY GOOGL",
    "DIGITALOCEAN COM AMSTERDAM USD 58 42",
    "SLACK T63PG8P6H DUBLIN USD 57 46",
    "SLACK T63PG8P6H DUBLIN USD 56 70",
    "SLACK T63PG8P6H DUBLIN USD 56 00",
    "SLACK T63PG8P6H DUBLIN USD 55 42",
    "SLACK T63PG8P6H DUBLIN USD 54 19",
    "SLACK T63PG8P6H DUBLIN USD 51 82",
    "SLACK T63PG8P6H DUBLIN USD 52 36",
    "OPENAI HTTPSOPENA USD 51 00",
    "CLAUDE AI SUBSCRIPTIONANTHROPIC USD 23 60",
    "OPENAI HTTPSOPENA USD 50 00",
    "GODADDY DOMAINS AN GURGAON",
    "EMI GODADDYMUMBAI",
    "WWW GODADDY COM",
    "EMI ANTHROPICANTHROPIC USD 29 50",
    "GODADDY DOMAINMUMBAI",
    "ADOBE SYSTEMS SOFTWARE I",
    "OPENAI HTTPSOPENA USD 25 00",
    "GODADDYMUMBAI",
    "STRIPE Z AISINGAPORE USD 18 00",
    "OPENAI HTTPSOPENA USD 10 00",
    "GODADDY DOMAINSMUMBAI",
    "GOOGLE WORKSPACEMUMBAI",
    "OPENAIOPENAI COM USD 11 80",
    "ANTHROPICANTHROPIC USD 11 80",
    "DIGITALOCEAN COM AMSTERDAM USD 10 92",
    "OPENAI HTTPSOPENA USD 10 25",
    "OPENAI HTTPSOPENA",
    "DIGITALOCEAN COM AMSTERDAM USD 9 94",
    "STRIPE Z AISINGAPORE USD 8 10",
    "DIGITALOCEAN COMAMSTERDAM USD 1 43",
    "DIGITALOCEAN COMAMSTERDAM USD 3 16",
    "DIGITALOCEAN COM AMSTERDAM USD 2 90",
    "DIGITALOCEAN COM AMSTERDAM USD 1 43",
    "DIGITALOCEAN COMAMSTERDAM USD 2 07",
]

# ------------------------------------------------ Subscriptions: Personal
SUBSCRIPTIONS_PERSONAL = [
    "NETFLIX NETFLIX",
    "NETFLIX",
    "NETFLIX DI SIMUMBAI",
    "NETFLIX ENTERTAINMENT SGURGAON",
]

# ------------------------------------------- Travel: Forex/Prepaid Cards
TRAVEL_FOREX = [
    "HDFC BANK PREPAID CARD",
    "HF80280921131730 HDFCBANKFOREXCARD",
]

# -------------------------------------------------------- Travel: Flights
TRAVEL_FLIGHTS = [
    "EMIRATES",
    "INDIGO AINE GURGAON",
    "EMI INDIGO AINEGURGAON",
    "TICKETS FLIG114504381 ABU DHABI",
    "INDIGO PAYTM",
]

# ------------------------------------------------- Travel: Hotels/Packages
TRAVEL_HOTELS_PACKAGES = [
    "ETI GLOBAL HOLIDAYS PVTMUMBAI",
    "MAKEMYTRIP L NEW",
    "MAKEMYTRIP LTGURGAON",
    "TPT TONYNAVIA TICKETS ETI GLOBAL HOLIDAYS",
    "MAKEMYTRIP NEW",
    "MACHAN RESORTS LLP",
    "EASE MY TRIP NEW",
    "MAKEMYTRIP LTNEW",
    "HOTEL VILLA DES GOUVERNEUPONDICHERR",
    "IXIGO",
    "TPT DOH TICKETS ETI GLOBAL HOLIDAYS",
    "CLEARTRIP LIMITEDMUMBAI",
    "TPT TONY NAVIA TICKETS ETI GLOBAL HOLIDAYS",
    "AGODA COM INTERNET",
    "AGODA",
    "AIRBNB PRIGURGAON",
    "UPI RAJESH R YESTP HDFC0007131 AIRBNB VALUE DT 30 11 2025",
    "AGODA COMPANY PTE",
    "EMI AIRBNB INDGURGAON",
    "AGODA COM THE MERCHA LONDON",
    "AIRBNB PVTGURGOAN",
    "PAYTM CLEARTRIPPRIVATE",
    "WWW AIRBNB COM GURGAON",
]

# ---------------------------------------------------------- Investments
INVESTMENTS_FD = ["FD THROUGH MOBILE TONY PIUS ALAPATT"]
INVESTMENTS_MUTUAL_FUNDS = [
    "TPT NORAH MUTUAL FUND NIPPON MULTI CAP FUND SUBSCRIPTION",
    "ICCLGROWW GROWW BSE GROWWPAY",
]
INVESTMENTS_CRYPTO = [
    "TONY PIUS ALAPATT SIBL XXXXXXXXXXXX2504 SAVE FROM SATOSHI",
    "AWLENCAN INNOVATIONS IBKL XXXXXXXXXXXX6569 ZEBPAY",
]
INVESTMENTS_CHIT_KURI = [
    "UPI XXXXXX7770 SBIN0008627 KURI",
    "UPI XXXXXX0005 SIBL0000517 KURI",
]

# ----------------------------------------------------------- Melvin fix
# See design spec: two specific transactions under "MELVIN MANOJ MATHEW
# MELVINMANOJ92" whose raw narration contains "loanrepayment" -- the
# rest of that merchant's transactions correctly stay Dining, so this is
# fixed by transaction id, not merchant pattern.
MELVIN_LOAN_FIX: dict[str, tuple[str, str]] = {
    "addd98a49577e4a7": ("Family & Friends", "Loans"),
    "67ee8f18e8565db8": ("Family & Friends", "Loans"),
}


def _build_subcategory_moves() -> dict[str, tuple[str, str]]:
    moves: dict[str, tuple[str, str]] = {}
    for pattern_list, category, subcategory in [
        (GROCERIES_MEAT, "Groceries", "Meat"),
        (GROCERIES_ALCOHOL, "Groceries", "Alcohol"),
        (GROCERIES_PRODUCE, "Groceries", "Produce"),
        (HEALTH_INSURANCE, "Health", "Insurance"),
        (DINING_DELIVERY, "Dining", "Delivery"),
        (DINING_OUT, "Dining", "Dining Out"),
        (TRANSPORT_FUEL_EXTRA, "Transport", "Fuel"),
        (TRANSPORT_CABS, "Transport", "Cabs/Rideshare"),
        (TRANSPORT_PUBLIC_TRANSIT, "Transport", "Public Transit"),
        (SUBSCRIPTIONS_BUSINESS_TOOLS, "Subscriptions", "Business Tools"),
        (SUBSCRIPTIONS_PERSONAL, "Subscriptions", "Personal"),
        (TRAVEL_FOREX, "Travel", "Forex/Prepaid Cards"),
        (TRAVEL_FLIGHTS, "Travel", "Flights"),
        (TRAVEL_HOTELS_PACKAGES, "Travel", "Hotels/Packages"),
        (INVESTMENTS_FD, "Investments", "FD/Deposits"),
        (INVESTMENTS_MUTUAL_FUNDS, "Investments", "Mutual Funds"),
        (INVESTMENTS_CRYPTO, "Investments", "Crypto"),
        (INVESTMENTS_CHIT_KURI, "Investments", "Chit/Kuri"),
    ]:
        for pattern in pattern_list:
            moves[pattern] = (category, subcategory)
    return moves


SUBCATEGORY_MOVES = _build_subcategory_moves()


def plan_migration(store) -> dict:
    """Read-only: compute what apply_migration() would change, without
    writing anything."""
    txns = store.all_transactions()
    by_id = {t.id: t for t in txns}

    pattern: dict[str, dict] = {}
    for p, destination in SUBCATEGORY_MOVES.items():
        expected_category, _ = destination
        matches = [t for t in txns
                  if t.merchant_norm == p or t.payee_handle == p]
        already_matches = all(t.category == expected_category for t in matches) \
            if matches else True
        pattern[p] = {
            "count": len(matches),
            "already_matches_category": already_matches,
            "destination": destination,
        }

    health_care_count = sum(
        1 for t in txns
        if t.category == HEALTH_CARE_DEFAULT_CATEGORY
        and t.merchant_norm not in HEALTH_INSURANCE
        and t.payee_handle not in HEALTH_INSURANCE
    )

    melvin_pending = sum(1 for tid in MELVIN_LOAN_FIX if tid in by_id)

    return {
        "pattern": pattern,
        "health_care_default": {"count": health_care_count},
        "melvin_fix": {"count": melvin_pending},
    }
