# POS Automation Framework

Ei folder ta ekta professional structure e organize kora - ekta boro file er bodole,
kaj onujayi alada alada file e vag kora hoyeche.

## Folder Structure

```
pos_framework/
├── config.py          <- Shudhu DATA (customer, item, invoice no, credentials).
│                         Kono value change korte hole EI FILE ta khulo.
│
├── pos_helpers.py      <- Generic reusable utility function (wait, retry-click,
│                         robust-press, row-selection logic). Shadharonoto
│                         change korar dorkar hoy na.
│
├── pos_actions.py      <- Business logic (login, transaction, hold/recall,
│                         exchange, return, payment, logout). Notun flow ba
│                         feature add korte hole EKHANE kaj korbe.
│
├── test_pos_full.py    <- Pytest TEST CASES. Shudhu test flow define kore,
│                         actual logic upor er duita file theke import kore.
│
├── requirements.txt    <- Python package list
└── README.md           <- Ei file
```

## Kono Change Korte Hole Kothay Jabe?

| Change korte chao                                  | Kon file khulbe   |
|-----------------------------------------------------|-------------------|
| Customer number, item barcode, invoice number       | `config.py`       |
| Notun transaction/customer add                      | `config.py`       |
| Login/Exchange/Return/Payment flow-e logic change    | `pos_actions.py`  |
| Wait time, retry count, click strategy               | `pos_helpers.py`  |
| Notun test case add (e.g. notun scenario)            | `test_pos_full.py`|

## Prothom Bar Setup

```bash
cd pos_framework
pip install -r requirements.txt
```

## Run Korar Niyom

Shob test (Login -> Transactions -> Hold/Recall -> Exchange -> Return -> Logout):

```bash
python -m pytest test_pos_full.py --alluredir=allure-results
```

Report dekhte:

```bash
allure serve allure-results
```

## Sudhu Nirdisto Test Run Korte Chaile

```bash
# Shudhu login test
python -m pytest test_pos_full.py::test_01_login

# Shudhu exchange test
python -m pytest test_pos_full.py::test_04_exchange_transaction

# Shudhu return test
python -m pytest test_pos_full.py::test_05_return_transaction
```

## Protibar Run Korar Age Mone Rakho

`config.py` file e:
- `EXCHANGE_TRANSACTION["invoice_no"]` - fresh/valid invoice number diye update koro
- `RETURN_TRANSACTION["invoice_no"]` - fresh/valid, na-return-kora invoice number diye update koro

Ei duita number app-e already exist kora, ekhono exchange/return na howa
invoice hote hobe - nahole test fail korte pare.
