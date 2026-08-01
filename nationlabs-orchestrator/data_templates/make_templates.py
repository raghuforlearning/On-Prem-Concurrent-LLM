"""Generate the two Excel templates (§10, §18) with sample rows + validation lists."""
import openpyxl
from openpyxl.worksheet.datavalidation import DataValidation
from pathlib import Path

OUT = Path(__file__).parent

# ---- vendor_master.xlsx (§10) ----
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "vendors"
headers = ["vendor_name", "tier", "tech_domains", "product_family", "contact_name",
           "job_title", "email", "phone", "country", "vendor_authorised",
           "deal_reg_capable", "role", "assigned_nl_owner", "contact_status",
           "last_validated"]
ws.append(headers)
ws.append(["Cisco", "OEM", "Networking; Wireless; Network security", "Catalyst/Meraki",
           "Jane Sales", "Account Manager", "jane.sales@cisco.com", "+9714XXXXXX",
           "UAE", 1, 1, "ACCOUNT_MANAGER", "raghu", "Verified", "2026-07-01"])
ws.append(["Ingram Micro", "DISTRIBUTOR", "Networking; Server and compute; Software subscription",
           "Multi-vendor", "Omar Disti", "Presales", "omar@ingrammicro.ae", "+9714YYYYYY",
           "UAE", 1, 1, "PRESALES", "raghu", "Verified", "2026-07-15"])

dv_tier = DataValidation(type="list", formula1='"OEM,DISTRIBUTOR,SUPPLIER,RESELLER"', allow_blank=False)
dv_status = DataValidation(type="list", formula1='"Verified,Unverified,Expired,Inactive,Duplicate,Missing,Under validation"')
dv_role = DataValidation(type="list", formula1='"ACCOUNT_MANAGER,SALES,PRESALES,DEAL_REG,ESCALATION"')
dv_bool = DataValidation(type="list", formula1='"0,1"')
ws.add_data_validation(dv_tier); ws.add_data_validation(dv_status)
ws.add_data_validation(dv_role); ws.add_data_validation(dv_bool)
dv_tier.add("B3:B500"); dv_status.add("N3:N500"); dv_role.add("L3:L500")
dv_bool.add("J3:K500")
for col, w in zip("ABCDEFGHIJKLMNO", [20,12,40,20,18,16,28,14,8,8,8,18,16,14,12]):
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A2"
wb.save(OUT / "vendor_master.xlsx")

# ---- ownership_matrix.xlsx (§18) ----
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "ownership"
ws.append(["tech_domain", "oem", "product_family", "primary_owner", "backup_owner",
           "commercial_owner", "technical_reviewer", "escalation_manager"])
ws.append(["Networking", "Cisco", None, "raghu", "ali", "finance1", "raghu", "presales_mgr"])
ws.append(["AI infrastructure", None, None, "raghu", None, "finance1", "raghu", "presales_mgr"])
for col, w in zip("ABCDEFGH", [24,14,18,14,14,16,18,18]):
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A2"
wb.save(OUT / "ownership_matrix.xlsx")

print("templates written:", OUT)
