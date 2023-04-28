# esri-fix-dashboards

This script is intended to be used for Oracle to PostgreSQL datasource migrations. When you overwrite a datasource
originally published from Oracle, all the field names will change from upper-case to lower-case. This breaks
AGO dashboards in strange ways, but if you modify all field name references to lower-case, it un-breaks them.

To use this script, point it at an AGO dashboard's itemid to run through it and change all found field names from
upper-case to lower-case.

Also note that you should know all data sources used in a dashboard first (because you already updated those
datasources from  a postgres overwrite right?) and put them in the var "expected_datasource_ids"
as a comma-separated list.

Example usage:

```
python .\main.py \
        --ago-user some_user \
        --ago-password password \
        --org-id your_org_id \
        --target_dashboard_itemid 123abc \
        --expected-datasource-itemids 456abc,789dfg
        --dry-run
        
# Double-check differences of your dashboard, names of the saved json will use the itemid:
diff 123abc-ORIGINAL-dashboard.json 123abc-MODIFIED-dashboard.json 

python .\main.py \
        --ago-user some_user \
        --ago-password password \
        --org-id your_org_id \
        --target_dashboard_itemid 123abc \
        --expected-datasource-itemids 456abc,789dfg
```