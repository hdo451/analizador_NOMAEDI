import sys
content = open('agents/document_processor.py').read()

old_4 = r"""            # Pattern 4: LatAm format with decimal comma and optional balance
            {
                'regex': r'(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\s+(.+?)\s+([-+]?\$?\s*\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d{2})|[-+]?\$?\s*\d+(?:[\.,]\d{2})?)(?:\s+([-+]?\$?\s*\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d{2})|[-+]?\$?\s*\d+(?:[\.,]\d{2})?))?$',
                'groups': {'date': 1, 'description': 2, 'amount': 3, 'balance': 4},
                'name': 'LatAm Comma Decimal'
            },

            # Pattern 5: ISO date plus free-form text, amount at the end
            {
                'regex': r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})\s+(.+?)\s+([-+]?\$?\s*\d{1,3}(?:[\.,]\d{3})*(?:[\.,]\d{2})|[-+]?\$?\s*\d+(?:[\.,]\d{2})?)$',
                'groups': {'date': 1, 'description': 2, 'amount': 3},
                'name': 'ISO Date Generic'
            }"""

new_4 = r"""            # Pattern 4: LatAm format with decimal comma and optional balance
            {
                'regex': r'(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\s+(.+?)\s+((?:[-+]?\$?\s*\d{1,3}(?:[\.,]\d{3})+(?:[\.,]\d{2})?|[-+]?\$\s*\d+(?:[\.,]\d{2})?|[-+]?\s*\d+[\.,]\d{2}))(?:\s+((?:[-+]?\$?\s*\d{1,3}(?:[\.,]\d{3})+(?:[\.,]\d{2})?|[-+]?\$\s*\d+(?:[\.,]\d{2})?|[-+]?\s*\d+[\.,]\d{2})))?$',
                'groups': {'date': 1, 'description': 2, 'amount': 3, 'balance': 4},
                'name': 'LatAm Formats'
            },

            # Pattern 5: ISO date plus free-form text, amount at the end
            {
                'regex': r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})\s+(.+?)\s+((?:[-+]?\$?\s*\d{1,3}(?:[\.,]\d{3})+(?:[\.,]\d{2})?|[-+]?\$\s*\d+(?:[\.,]\d{2})?|[-+]?\s*\d+[\.,]\d{2}))$',
                'groups': {'date': 1, 'description': 2, 'amount': 3},
                'name': 'ISO Date Generic'
            }"""

if old_4 in content:
    content = content.replace(old_4, new_4)
    open('agents/document_processor.py', 'w').write(content)
    print("Replaced!")
else:
    print("Not found")

