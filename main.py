import gzip
import requests
import json
import re
import urllib.parse


def main(itemid, new_datasource_itemid=None):
    """Takes a dashboard of {itemid}, gets it's JSON, finds field names and makes them lower-case,
    then posts it back to AGO.
    Optionally takes a new itemid for a new datasource, and updates it in-line as well. Likely of limited use
    since dashboards can have multiple datasources."""

    token_url = 'https://arcgis.com/sharing/rest/generateToken'
    data = {'username': 'ago-user',
            'password': 'password',
            'referer': 'https://www.arcgis.com',
            'f': 'json'}
    ago_token = requests.post(token_url, data).json()['token']

    # Our unique AGO organization id
    org_id = 'some_org_id'

    # Request the "data" json which contains field names and actual meat of the dashboard
    data_url = f'https://www.arcgis.com/sharing/rest/content/items/{itemid}/data'
    params = {
        'f': 'json',
        'token': ago_token
    }
    response = requests.get(data_url, params=params)
    #print(response.text)
    assert response.status_code == 200
    parsed_json = json.loads(response.text)
    #print(json.dumps(parsed_json, indent=2))

    # Save all found field names in a set so we can later come back and modify "expression" and "text" elements
    # intelligently without having to worry about complex regex or string manipulation.
    found_field_names = set()
    found_datasource_itemids = set()

    # Recursive function to run through and modify field names as we go
    def find_and_modify_field_names(json_obj):
        # If the value we're on is a dictionary, check keys and potentially recurse on the value.
        if isinstance(json_obj, dict):
            for key, value in json_obj.items():
                if key == "dataSource":
                    if json_obj["dataSource"]["type"] == 'itemDataSource':
                        found_datasource_itemids.add(json_obj["dataSource"]["itemId"])
                    if json_obj["dataSource"]["layerId"] == 0 and new_datasource_itemid:
                        json_obj["dataSource"]["itemId"] = new_datasource_itemid
                    elif json_obj["dataSource"]["layerId"] != 0 and found_datasource_itemids:
                        # Safety check for specific calls to layers within a dataSource that aren't simply 0
                        # If it's not using the first layer, which is 0, then fail out.
                        # We should not modify programmatically in this case.
                        raise Exception(f'''
                                Found a specific layerId reference: {str(value)}!'
                                Cannot update with new datasource itemId programmatically! Please make your itemId
                                changes manually through assistant.esri-ps.com.
                                ''')

                # if we have a field key, then the sub value is also a dict containing info about that field.
                if key == "field":
                    if json_obj["field"]["name"]:
                        field_name = json_obj["field"]["name"]
                        found_field_names.add(field_name.upper())
                        json_obj["field"]["name"] = field_name.lower()

                # This has a direct field name value, lower-case if not empty
                if key == "fieldName":
                    if value:
                        found_field_names.add(value.upper())
                        json_obj[key] = value.lower()

                # This has a direct field name value, lower-case if not empty
                if key == "onStatisticField":
                    if value:
                        found_field_names.add(value.upper())
                        json_obj[key] = value.lower()

                # This has a direct field name value, lower-case if not empty
                if key == "valueField":
                    # absoluteValue can sometimes be here, and is used by pie charts
                    if value and str(value) != 'absoluteValue':
                        found_field_names.add(value.upper())
                        json_obj[key] = value.lower()

                # fieldMap maps fields to another, which contain sourceName and targetName
                # Direct field name value in that case
                if key == "sourceName":
                    # absoluteValue can sometimes be here, and is used by pie charts
                    if value:
                        found_field_names.add(value.upper())
                        json_obj[key] = value.lower()
                if key == "targetName":
                    # absoluteValue can sometimes be here, and is used by pie charts
                    if value:
                        found_field_names.add(value.upper())
                        json_obj[key] = value.lower()

                # groupByFields is a list of fields, even if one value, loop through to make a new lowercase list
                # And reassign.
                if key == "groupByFields":
                    if value:
                        if type(value) is list:
                            newGroupList = []
                            for i in value:
                                found_field_names.add(i.upper())
                                newGroupList.append(i.lower())
                            json_obj[key] = newGroupList
                        else:
                            json_obj[key] = value.lower()

                # valueFields is a list of fields, even if one value, loop through to make a new lowercase list
                # And reassign. Seems to be a companion item to "expressions" describing what fields it uses.
                if key == "valueFields":
                    if value:
                        if type(value) is list:
                            newGroupList = []
                            for i in value:
                                found_field_names.add(i.upper())
                                newGroupList.append(i.lower())
                            json_obj[key] = newGroupList
                        else:
                            json_obj[key] = value.lower()

                # orderByFields is a list containing values like this: "FIELD DESC"
                if key == 'orderByFields':
                    if value:
                        if type(value) is list:
                            newGroupList = []
                            for i in value:
                                # Split by space, then rejoin once we lowercase the field name
                                isplit = i.split(' ')
                                found_field_names.add(isplit[0].upper())
                                isplit[0] = isplit[0].lower()
                                joined = ' '.join(isplit)
                                newGroupList.append(joined)
                            json_obj[key] = newGroupList
                        else:
                            json_obj[key] = value.lower()

                # seriesOrderByFields is a list containing values like this: "FIELD ASC"
                if key == 'seriesOrderByFields':
                    if value:
                        if type(value) is list:
                            newGroupList = []
                            for i in value:
                                # Split by space, then rejoin once we lowercase the field name
                                isplit = i.split(' ')
                                found_field_names.add(isplit[0].upper())
                                isplit[0] = isplit[0].lower()
                                joined = ' '.join(isplit)
                                newGroupList.append(joined)
                            json_obj[key] = newGroupList
                        else:
                            json_obj[key] = value.lower()

                if key == "text":
                    # Use found_field_names set to replace field name strings with the lower_case version.
                    # NOTE: need to grab field names from source layers, we won't always find field names elsewhere.
                    if value:
                        for i in found_field_names:
                            # Using regex, find all 'i' strings, and then substitute out a lower-case version
                            # ignore case otherwise several similar field names will result in inconsistent case.
                            # Also all we care about in "text" fields are field names surrounded by curly braces,
                            # so only search and replace for that
                            pattern = re.compile('{' + i + '}', re.IGNORECASE)
                            value = pattern.sub('{' + i.lower() + '}', value)
                        json_obj[key] = value

                if key == 'expression':
                    # Use found_field_names set to replace field name strings with the lower_case version.
                    if value:
                        for i in found_field_names:
                            # Using regex, find all 'i' strings, and then substitute out a lower-case version
                            # ignore case otherwise several similar field names will result in inconsistent case.
                            pattern = re.compile(i, re.IGNORECASE)
                            value = pattern.sub(i.lower(), value)
                        json_obj[key] = value

                else:
                    # Continue recursion on value to keep going down the JSON tree
                    find_and_modify_field_names(value)
        elif isinstance(json_obj, list):
            # loop through items if list and recurse on that.
            for item in json_obj:
                find_and_modify_field_names(item)

    def gather_datasource_field_names():
        """Using our found datasource itemids, collect all field names for the datasource. Ths is important because
        "text" and "expression" values can contain field names not used anywhere else where we would have recorded them
         in our first run of find_and_modify_field_names()."""
        for i in found_datasource_itemids:
            search_url = 'https://www.arcgis.com/sharing/rest/search'
            params = {'f': 'json',
                      'q': i,
                      'token': ago_token
                      }
            response = requests.get(search_url, params=params)

            #print(json.dumps(response.json(), indent=2))
            if response.json()["results"][0]["type"] == 'Table' or response.json()["results"][0]["type"] == 'Feature Layer' or response.json()["results"][0]["type"] == 'Feature Service':
                # Loop through all layers
                for layer in response.json()["results"]:
                    dataset_name = layer["name"]
                    # We can query for datasource json and get field names that way:
                    datasource_url = f'https://services.arcgis.com/{org_id}/ArcGIS/rest/services/{dataset_name}/FeatureServer/0?f=pjson&token={ago_token}'
                    response2 = requests.get(datasource_url)
                    #print(json.dumps(response2.json(), indent=2))
                    for i in response2.json()['fields']:
                        field_name = i['name']
                        # Add to our found_field_names set for use in our 2nd run of find_and_modify_field_names()
                        found_field_names.add(field_name.upper())

    # first run where we get datasource itemids and field names used in the dashboard json.
    find_and_modify_field_names(parsed_json)

    print(f'found_datasource_itemids: {found_datasource_itemids}')
    gather_datasource_field_names()
    print(f'found_field_names: {found_field_names}')

    # Run a second time after our found_field_names set is fully populated
    find_and_modify_field_names(parsed_json)


    f = open('./new_dashboard_json.txt', "w")
    # Write with indent so it's readable while I'm spot-checking
    f.write(json.dumps(parsed_json, indent=2))
    f.close()


    # Once we have our updated json, update the dashboard with it
    regular_json = json.dumps(parsed_json)
    encoded_json = urllib.parse.quote(json.dumps(parsed_json))
    compressed_data = gzip.compress(json.dumps(parsed_json).encode('utf-8'))

    form_data = {
        'f': 'json',
        'id': itemid,
        'token': ago_token,
        'text': regular_json
    }
    encoded_form_data = urllib.parse.urlencode(form_data)


    update_url = f'https://www.arcgis.com/sharing/rest/content/users/maps.phl.data/items/{itemid}/update'
    print(update_url)

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    response = requests.post(update_url, headers=headers, data=encoded_form_data)
    print(response.text)
    assert response.status_code == 200


if __name__ == '__main__':
    itemid = 'some_dashboard_itemid'
    #optional_new_datasource_itemid = 'optional_new_datasource_itemid'

    main(itemid)