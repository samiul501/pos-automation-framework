
# Purchase Rules

## PR

- Required fields must be validated.
- Approval is required before PO conversion.

## PO

- PO should reference the correct PR.
- Approved PO should be available for receiving.
- Received quantity must follow configured limits.

## GRN

- GRN should update inventory.
- GRN quantity must be validated against PO quantity.

## Accounting

- Generated journal must be balanced.
- Total Debit must equal Total Credit.
