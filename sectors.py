"""
NSE Sector Definitions
──────────────────────
To add a new sector: just add a new key-value pair to SECTORS dict.
To add a stock to a sector: add its symbol (without .NS) to the list.
"""

SECTORS = {

    "Nifty 50": [
        "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
        "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BPCL", "BHARTIARTL",
        "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT",
        "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE",
        "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK",
        "INFY", "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK",
        "LT", "LTIM", "M&M", "MARUTI", "NESTLEIND",
        "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE",
        "SHRIRAMFIN", "SBIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS",
        "TATASTEEL", "TCS", "TECHM", "TITAN", "ULTRACEMCO",
    ],

    "Nifty 500": None,  # None = use full nse500_symbols list

    "Banking & Finance": [
        "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
        "INDUSINDBK", "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "RBLBANK",
        "CUB", "KARURVYSYA", "J&KBANK", "INDIANB", "BANKBARODA",
        "BANKINDIA", "CENTRALBK", "IOB", "UCOBANK", "MAHABANK",
        "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "M&MFIN", "MANAPPURAM",
        "MUTHOOTFIN", "LICHSGFIN", "PNBHOUSING", "CANFINHOME", "AAVAS",
        "HOMEFIRST", "APTUS", "FIVESTAR", "CREDITACC", "SBFC",
        "HDBFS", "POONAWALLA", "SHRIRAMFIN", "JIOFIN", "ABCAPITAL",
        "IDBI", "PNB", "SBICARD", "SBILIFE", "HDFCLIFE",
        "ICICIPRULI", "ICICIGI", "STARHEALTH", "GODIGIT", "NIACL",
        "GICRE", "LICI", "CANHLIFE", "MFSL", "NIVABUPA",
    ],

    "IT & Technology": [
        "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM",
        "LTIM", "MPHASIS", "COFORGE", "PERSISTENT", "OFSS",
        "CYIENT", "KPITTECH", "ZENSARTECH", "SONATSOFTW", "NEWGEN",
        "INTELLECT", "LATENTVIEW", "NETWEB", "DATAPATTNS", "SYRMA",
        "KAYNES", "DIXON", "AMBER", "BSOFT", "ECLERX",
    ],

    "Pharma & Healthcare": [
        "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN",
        "AUROPHARMA", "ALKEM", "TORNTPHARM", "IPCALAB", "GLENMARK",
        "MANKIND", "EMCURE", "JBCHEPHARM", "NATCOPHARM", "GRANULES",
        "LAURUSLABS", "NEULANDLAB", "CONCORDBIO", "GLAND", "PPLPHARMA",
        "CAPLIPOINT", "AJANTPHARM", "ERIS", "WOCKPHARMA", "PFIZER",
        "GLAXO", "ABBOTINDIA", "SYNGENE", "POLYMED", "RAINBOW",
        "APOLLOHOSP", "FORTIS", "MAXHEALTH", "MEDANTA", "NH",
        "KIMS", "ASTERDM",
    ],

    "Auto & Auto Ancillaries": [
        "MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "HEROMOTOCO",
        "EICHERMOT", "TVSMOTO", "ASHOKLEY", "FORCEMOT", "ESCORTS",
        "HYUNDAI", "MOTHERSON", "BOSCHLTD", "MINDA", "BHARATFORG",
        "ENDURANCE", "APOLLOTYRE", "CEATLTD", "BALKRISIND", "JKTYRE",
        "EXIDEIND", "AMARA", "SCHAEFFLER", "TIMKEN", "GABRIEL",
        "UNOMINDA", "SONACOMS", "TIINDIA", "RKFORGE", "JBMA",
        "MINDACORP", "MSUMI", "BELRISE",
    ],

    "FMCG & Consumer": [
        "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR",
        "MARICO", "COLPAL", "EMAMILTD", "GODREJCP", "TATACONSUM",
        "UNITDSPR", "UBL", "RADICO", "GODFRYPHLP", "GILLETTE",
        "BAJAJCON", "PATANJALI", "BIKAJI", "CCL", "ZYDUSWELL",
        "HONASA", "VBL", "DEVYANI", "JUBLFOOD", "SAPPHIRE",
        "WESTLIFE",
    ],

    "Metals & Mining": [
        "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "HINDZINC",
        "COALINDIA", "NMDC", "SAIL", "JINDALSTEL", "JSL",
        "JINDALSAW", "WELCORP", "NATIONALUM", "HINDCOPPER", "NSLNISP",
        "GPIL", "GALLANTT", "SHYAMMETL", "GRAVITA", "HEG",
        "GRAPHITE", "MOIL", "NAVA", "JAINREC",
    ],

    "Energy & Power": [
        "RELIANCE", "ONGC", "BPCL", "HINDPETRO", "IOC",
        "GAIL", "PETRONET", "MRPL", "CHENNPETRO", "SPLPETRO",
        "NTPC", "POWERGRID", "TATAPOWER", "ADANIPOWER", "ADANIGREEN",
        "ADANIENSOL", "ATGL", "IGL", "MGL", "GSPL",
        "JSWENERGY", "TORNTPOWER", "CESC", "RPOWER", "JPPOWER",
        "NHPC", "SJVN", "IREDA", "NTPCGREEN", "WAAREEENER",
        "EMMVEE", "INOXWIND", "SUZLON", "PREMIRENERGY", "ATHERENERG",
        "ACMESOLAR",
    ],

    "Infrastructure & Construction": [
        "LT", "ULTRACEMCO", "SHREECEM", "AMBUJACEM", "ACC",
        "DALBHARAT", "RAMCOCEM", "NUVOCO", "JKCEMENT", "JSWCEMENT",
        "HEIDELBERG", "ORIENTCEM", "HSCL", "NCC", "NBCC",
        "ENGINERSIN", "IRCON", "RITES", "KPIL", "AFCONS",
        "IRB", "TITAGARH", "HUDCO", "RVNL", "RAILTEL",
        "IRFC", "IRCTC", "GRSE", "COCHINSHIP", "MAZDOCK",
        "BDL", "BEL", "HAL", "BEML",
    ],

    "Real Estate": [
        "DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "BRIGADE",
        "SOBHA", "LODHA", "PHOENIXLTD", "ANANTRAJ", "MAHLIFE",
        "CHALET", "JUBLINGREA", "KOLTEPATIL", "NUVOCO", "SIGNATURE",
        "URBANCO",
    ],

    "Capital Goods & Engineering": [
        "ABB", "SIEMENS", "HAVELLS", "CGPOWER", "BHEL",
        "THERMAX", "CUMMINSIND", "KIRLOSENG", "ELGIEQUIP", "ELECON",
        "KPRMILL", "KEI", "POLYCAB", "FINCABLES", "RRKABEL",
        "HBLENGINE", "TDPOWERSYS", "AIAENG", "CARBORUNIV", "GRINDWELL",
        "SCHNEIDER", "POWERINDIA", "GVT&D", "TRITURBINE", "KEC",
        "KALPATPOWR", "TECHNO", "JYOTICNC", "CRAFTSMAN", "LLOYDSME",
    ],

    "Chemicals & Fertilizers": [
        "PIDILITIND", "DEEPAKNTR", "NAVINFLUOR", "FLUOROCHEM", "SRF",
        "AAVAS", "AARTIIND", "CLEAN", "SUMICHEM", "PIIND",
        "COROMANDEL", "CHAMBLFERT", "DEEPAKFERT", "FACT", "PARADEEP",
        "EIDPARRY", "BALRAMCHIN", "DHANUKA", "RALLIS", "BAYERCROP",
        "PCBL", "DCMSHRIRAM", "TATACHEM",
    ],

    "Telecom & Media": [
        "BHARTIARTL", "BHARTIHEXA", "IDEA", "TTML", "TEJASNET",
        "HFCL", "RAILTEL", "ITI", "INDUSTOWER", "SUNTV",
        "ZEEL", "SAREGAMA", "PVRINOX",
    ],

    "Retail & E-Commerce": [
        "DMART", "TRENT", "NYKAA", "FIRSTCRY", "ETERNAL",
        "SWIGGY", "PAYTM", "CARTRADE", "INDIAMART", "MEESHO",
        "LENSKART", "NAUKRI", "POLICYBZR", "ANGELONE", "GROWW",
    ],

    "Logistics & Shipping": [
        "CONCOR", "BLUEDART", "DELHIVERY", "GESHIP", "SCI",
        "COCHINSHIP", "AEGISLOG", "AEGISVOPAK", "TRAVELFOOD", "TBOTEK",
        "REDINGTON",
    ],

    "Paints & Chemicals": [
        "ASIANPAINT", "BERGEPAINT", "KANSAINER", "AKZOINDIA", "INDIGO",
        "JSWDULUX", "PIDILITIND",
    ],

    "Textiles": [
        "PAGEIND", "TRIDENT", "WELSPUNLIV", "VARDHMAN", "RAYMOND",
        "KPRMILL", "SAPPHIRE", "SIYARAM", "ARVIND", "GOKEX",
    ],

    "PSU": [
        "SBIN", "BANKBARODA", "BANKINDIA", "CANBK", "INDIANB",
        "UNIONBANK", "MAHABANK", "IOB", "UCOBANK", "CENTRALBK",
        "PNB", "NTPC", "POWERGRID", "ONGC", "BPCL",
        "IOC", "GAIL", "COALINDIA", "NMDC", "SAIL",
        "BEL", "HAL", "BHEL", "GRSE", "MAZDOCK",
        "COCHINSHIP", "IRCTC", "IRFC", "RVNL", "HUDCO",
        "RECLTD", "PFC", "IREDA", "NBCC", "NCC",
        "ENGINERSIN", "IRCON", "RITES", "RAILTEL", "NHPC",
        "SJVN", "LICI", "GICRE", "NIACL",
    ],

}
