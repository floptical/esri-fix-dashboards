import json
import requests
import click
from deepdiff import DeepDiff
import re
import urllib.parse
from urllib.parse import urlencode

def generate_token(username, password, org_id):
    """Generates an ArcGIS Online token."""
    url = 'https://arcgis.com/sharing/rest/generateToken'

    payload = {
        'username': username,
        'password': password,
        'referer': 'https://arcgis.com',
        'f': 'json'
    }
    encoded_payload = urlencode(payload)
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    response = requests.post(url, data=encoded_payload, headers=headers)
    response.raise_for_status()
    token_data = response.json()
    if "error" in token_data:
        raise ValueError(f"Error generating token: {token_data['error']}")
    return token_data['token'] 

def fetch_dashboard_data(org_id, token, dashboard_itemid):
    """Fetches the dashboard configuration JSON."""
    url = f"https://{org_id}.maps.arcgis.com/sharing/rest/content/items/{dashboard_itemid}/data"
    params = {'token': token, 'f': 'json'}
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

def save_json(data, file_path):
    with open(file_path, 'w') as file:
        json.dump(data, file, indent=4)

def get_field_names_from_arcgis(itemid, layer_num, ago_rest_name, token, org):
    #url = f"https://www.arcgis.com/sharing/rest/content/items/{itemid}/data"
    url = f"https://services.arcgis.com/{org}/ArcGIS/rest/services/{ago_rest_name}/FeatureServer/{layer_num}"
    print(f'Attempting to get fields from {url}')
    params = {'token': token, 'f': 'pjson'}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        try:
            # Attempt to parse the response as JSON
            metadata = response.json()
        except requests.exceptions.JSONDecodeError:
            raise ValueError(f"Failed to parse JSON response: {response.text}")
        # Initialize an empty list to hold field names
        field_names = [f['name'] for f in metadata.get('fields', []) if f.get('name')]

        fields_to_remove_if_exist = ['CreationDate', 'Creator', 'EditDate', 'Editor']
        # Remove unwanted fields if they exist
        for field in fields_to_remove_if_exist:
            if field in field_names:
                field_names.remove(field)

        if not field_names:
            raise ValueError(f"No field names found in the response: {response.text}, are you using the correct layer number?")
        return field_names
    else:
        raise Exception(f"Failed to fetch field names for itemId {itemid}: {response.text}")
    

def save_json_to_file(data, filename):
    """Saves JSON data to a local file."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


def lowercase_fields(data, target_itemid, field_names, unsafe_mode):
    field_pattern = re.compile(r'\b(' + '|'.join(re.escape(field) for field in field_names) + r')\b', re.IGNORECASE)

    keys_to_check = [
        'field', 'x', 'field1', 'field2', 'fieldName', 'text', 
        'onStatisticField', 'absoluteValue', 'name',
        'expression', "sourceName", "targetName", "valueField", "definitionExpression"
    ]
    special_list_keys = [
        'orderByFields', 'seriesOrderByFields', "valueFields"
    ]

    # List to store valid arcade data source IDs that we identify as referencing our feature class itemid only.
    valid_arcade_datasource_ids = []
    
    def search_and_modify(sub_structure):
        """Recursively searches for the key_to_modify and updates its value."""

        if isinstance(sub_structure, dict):
            for key, value in sub_structure.items():
                if isinstance(value, dict):
                    search_and_modify(value)
                elif key in keys_to_check and value:
                    #print(f'\n(1)Checking {sub_structure[key]} in key {key}')
                    # Use regex to modify only text in the string that is the field name.
                    sub_structure[key] = field_pattern.sub(lambda match: next(field for field in field_names if field.lower() == match.group(0).lower()), value)
                    #print(sub_structure[key])
                elif key in special_list_keys and isinstance(value, list):
                    # Modify strings in lists under special_list_keys
                    #print(f'\n(2)Checking {sub_structure[key]} in key {key}')
                    sub_structure[key] = [
                        field_pattern.sub(lambda match: next(field for field in field_names if field.lower() == match.group(0).lower()), value) if isinstance(v, str) else v
                        for v in value
                    ]
                    #print(sub_structure[key])
                else:
                    search_and_modify(value)
        elif isinstance(sub_structure, list):
            for item in sub_structure:
                search_and_modify(item)

    def find_and_process_structure(structure):
        """Find JSON structures that have our data source itemID in a key called "itemDataSource" or "arcadeDataSource" or "itemid" at the top level.
        When we find them, only then do we recursively crawl through that JSON structure and attempt to lower-case found field names."""

        if isinstance(structure, dict):
            # Analyze arcadeDataSourceItems for script key, and try to find our datasource itemid in it.
            # Also make sure there aren't other item datasources, otherwise you should modify this dashboard by hand.
            if 'arcadeDataSourceItems' in structure:
                found_itemids = set()
                # Look for hexadecimal values with a length of 32 in the script (itemids)
                regex = re.compile(r'([0-9a-fA-F]{32})')
                for arcadeSource in structure["arcadeDataSourceItems"]:
                    matches = regex.findall(arcadeSource["script"])
                    for match in matches:
                        found_itemids.add(match)
                    # If we have more than one itemid within an arcadedatasource, then we don't want to touch this
                    # because that means we can't selectively change the fields for one specific datasource.
                    if len(found_itemids) > 1:
                        raise Exception(f'Found more than one itemid in {arcadeSource["itemId"]}, we dont want to mess with this.')
                    if len(found_itemids) == 0:
                        print(f'No datasources found in {arcadeSource["itemId"]} ??')
                    elif len(found_itemids) == 1:
                        # If we're sure only our target itemid is referenced by the arcade data source
                        if target_itemid in found_itemids:
                            valid_arcade_datasource_ids.append(arcadeSource["itemId"])
                            print(f'Found arcadeDataSource itemId {arcadeSource["itemId"]}!\n')

            # now modify the "script" key itself if we're sure it references only our source itemid
            if 'arcadeDataSourceItems' in structure:
                for arcadeSource in structure["arcadeDataSourceItems"]:
                    if arcadeSource['itemId'] in valid_arcade_datasource_ids:
                        #print(f'Modifying arcadeDataSource script for {arcadeSource["itemId"]}!\n')
                        # Use regex to modify only text in the string that is the field name.
                        arcadeSource['script'] = field_pattern.sub(lambda match: match.group(0).lower(), arcadeSource['script'])
                        #print(arcadeSource['script'])

            # Loop through and identify structures we can modify
            if 'itemId' in structure and structure['itemId'] == target_itemid:
                print('Found matching itemId, modifying it.')
                search_and_modify(structure)
            if (
                'datasets' in structure and
                len(structure['datasets']) == 1 and
                isinstance(structure['datasets'], list) 
            ):
                if structure['datasets'][0]["dataSource"] and 'itemId' in structure['datasets'][0]["dataSource"].keys():
                    if structure['datasets'][0]["dataSource"]['itemId'] == target_itemid:
                        print('Found "datasets" struct, modifying it.')
                        search_and_modify(structure)
            if (
                'dataSource' in structure and
                isinstance(structure['dataSource'], dict) and
                structure['dataSource'].get('type') == 'itemDataSource' and
                structure['dataSource'].get('itemId') == target_itemid
            ):
                print('Found "itemDataSource" struct, modifying it.')
                search_and_modify(structure)
            elif (
                'dataSource' in structure and
                isinstance(structure['dataSource'], dict) and
                structure['dataSource'].get('type') == 'arcadeDataSource' and
                structure['dataSource'].get('itemId') in valid_arcade_datasource_ids
            ):
                print('Found "arcadeDataSource" struct, modifying it.')
                search_and_modify(structure)
            else:
                for value in structure.values():
                    find_and_process_structure(value)
        # Recurse on ourselves
        elif isinstance(structure, list):
            for item in structure:
                find_and_process_structure(item)

    # Start processing the JSON data
    if unsafe_mode:
        search_and_modify(data)
    else:
        find_and_process_structure(data)
    return data


def update_dashboard(token, dashboard_itemid, updated_json):
        regular_json = json.dumps(updated_json)
        #encoded_json = urllib.parse.quote(json.dumps(parsed_json))
        #compressed_data = gzip.compress(json.dumps(parsed_json).encode('utf-8'))

        form_data = {
            'f': 'json',
            'id': dashboard_itemid,
            'token': token,
            'text': regular_json
        }
        # Seems to be necessary to encode it all, otherwise we get an error about our URI being too long
        # since the entire json contents are passed in the URL, encoding makes it more compact I believe?
        encoded_form_data = urllib.parse.urlencode(form_data)

        update_url = f'https://www.arcgis.com/sharing/rest/content/users/maps.phl.data/items/{dashboard_itemid}/update'
        print(update_url)

        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = requests.post(update_url, headers=headers, data=encoded_form_data)
        print(response.text)
        assert response.status_code == 200
        if 'success' in response.text:
            print('Dashboard successfully updated.')
        else:
            print('Failure???')


def get_item_owner(base_url, token, item_id):
    url = f"{base_url}/content/items/{item_id}"
    params = {
        "f": "json",
        "token": token
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    item_info = response.json()
    return item_info.get("owner")


def transfer_ownership(base_url, token, item_id, current_owner, new_owner):
    url = f"{base_url}/content/users/{current_owner}/items/{item_id}/reassign"
    data = {
        "targetUsername": new_owner,
        "f": "json",
        "token": token
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    result = response.json()
    if "success" in result and result["success"]:
        print(f"Ownership of item {item_id} successfully transferred to {new_owner}")
    else:
        print(f"Failed to transfer ownership: {result}")


@click.command()
@click.option('--ago-user', required=True, help="ArcGIS Online username.")
@click.option('--ago-password', required=True, help="ArcGIS Online password.")
@click.option('--org-id', required=True, help="ArcGIS Online organization ID.")
@click.option('--target-dashboard-itemid', required=True, help="The item ID of the dashboard to modify.")
@click.option('--target-datasource-itemid', required=True, help="The item ID of the datasource to target.")
@click.option('--target-datasource-layer-num', required=False, default=0, help="The layer number of the datasource, usuall 0 but can differ sometimes from publishing wackiness.")
@click.option('--target-datasource-rest-name', required=True, help="It's REST name so we can get the field names.")
@click.option('--unsafe-mode', is_flag=True, help="Don't use safety checks such as making sure top level of a key has proper datasource.")
@click.option('--dry-run', is_flag=True, help="Perform a dry run without uploading changes.")
def main(ago_user, ago_password, org_id, target_dashboard_itemid, target_datasource_itemid, target_datasource_layer_num, target_datasource_rest_name, unsafe_mode, dry_run):
    """Main function to modify dashboard JSON and update it on ArcGIS Online.
    Will look for the target data source itemId in the JSON and lowercase all field names for that source only.
    Should do this safely as we very specifically target only certain keys that should containe field references.
    """

    token = generate_token(ago_user, ago_password, org_id)

    og_owner = get_item_owner("https://www.arcgis.com/sharing/rest", token, target_dashboard_itemid)
    if og_owner != ago_user:
        print(f'\nOwner of {target_dashboard_itemid} is {og_owner}, will attempt to swap ownership if not using --dry-run.\n')
    if not og_owner:
        print(f'Couldn\'t grab the owner of {target_dashboard_itemid}, exiting...')
    if og_owner == 'None':
        print(f'Couldn\'t grab the owner of {target_dashboard_itemid}, exiting...')

    # Fetch field names for the target itemId
    field_names = get_field_names_from_arcgis(target_datasource_itemid, target_datasource_layer_num, target_datasource_rest_name, token, org_id)
    print(f'\n{field_names}\n')

    # Get the dashboard JSON data
    original_json = fetch_dashboard_data(org_id, token, target_dashboard_itemid)
    # Create a deep copy to modify
    copy_json = json.loads(json.dumps(original_json))
    # Save a backup of the original and modified JSON locally
    save_json_to_file(original_json, f"{target_dashboard_itemid}_original_dashboard.json")

    # Perform the field name modifications
    modified_json = lowercase_fields(copy_json, target_datasource_itemid, field_names, unsafe_mode)

    # Compare the original and modified JSON
    differences = DeepDiff(original_json, modified_json, ignore_order=True)

    # Print differences
    if differences:
        print("Differences between the original and modified JSON:")
        save_json_to_file(modified_json, f"{target_dashboard_itemid}_modified_dashboard.json")
        print(json.dumps(differences, indent=4))
    else:
        print("No differences found. The JSON structure remains unchanged.")

    if not differences:
        print('No changes were made to the JSON structure, won\'t attempt to update the dashboard in AGO.')
    else:
        if dry_run:
            print("Dry run complete. Modified JSON saved locally.")
        else:
            # Update dashboard on ArcGIS Online
            if og_owner != ago_user:
                print(f'You do not own {target_dashboard_itemid}, attempting to transfer ownership to you.')
                transfer_ownership("https://www.arcgis.com/sharing/rest", token, target_dashboard_itemid, current_owner=og_owner, new_owner=ago_user)
            response = update_dashboard(token, target_dashboard_itemid, modified_json)
            if og_owner != ago_user:
                transfer_ownership("https://www.arcgis.com/sharing/rest", token, target_dashboard_itemid, current_owner=ago_user, new_owner=og_owner)

if __name__ == "__main__":
    main()
