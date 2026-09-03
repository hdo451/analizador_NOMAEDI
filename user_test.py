from agents.document_processor import DocumentProcessorAgent
agent = DocumentProcessorAgent()

text = """
ACCOUNT HOLDER STATEMENT SUMMARY
Jordan M. Calloway Opening Balance Mar 1 $12,450.33
4712 Ridgewood Terrace Total Credits (+) $9,202.37
Germantown, MD 20876 Total Debits (−) $6,707.63
Closing Balance Mar 31 $14,945.07
CHECKING ACCOUNT
Account #: **** **** 8831 CREDIT CARD LINKED
Routing #: 0550-1234-7 Meridian Rewards Visa ****4419
Account Type: Premier Checking Statement Balance: $1,847.62
Min. Payment Due: $37.00
TRANSACTION DETAIL — MARCH 2025
DATE DESCRIPTION TYPE AMOUNT BALANCE
03/01/2025 OPENING BALANCE — $12,450.33
03/03/2025 ACH PYMT PAYROLL NORTHGATE TECH LLC DEP +$8,000.00 $20,450.33
03/03/2025 AUTOPAY MORTGAGE SVC #77421 FHLMC DBT -$1,850.00 $18,600.33
03/03/2025 WF AUTOPAY LOC PMT *8847 DBT -$320.00 $18,280.33
03/04/2025 WHOLEFDS MKT #0472 ROCKVILLE MD DBT -$94.17 $18,186.16
03/04/2025 AMZN MKTP US*2K9F4R1Z3 CRD -$38.49 $18,147.67
03/05/2025 EXXONMOBIL 97423100 GAITHERSBURG MD DBT -$62.30 $18,085.37
03/05/2025 NETFLIX.COM 866-579-7172 CA CRD -$22.99 $18,062.38
03/06/2025 SQ *SWEETGREEN #114 BETHESDA MD CRD -$16.75 $18,045.63
03/10/2025 COSTCO WHSE #0471 GERMANTOWN MD DBT -$247.19 $17,326.60
03/12/2025 TST*FOUNDING FARMERS #2 DC CRD -$143.80 $16,759.05
"""

lines = text.split('\n')
for i, line in enumerate(lines):
    if agent._looks_like_transaction(line):
        pt = agent._parse_single_transaction(line)
        if pt:
            print(f"Parsed: {pt['date']} | {pt['description']} | Amt: {pt['amount']} | Bal: {pt['balance']}")
        else:
            print(f"Failed to parse line {i}: {line}")
