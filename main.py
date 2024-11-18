import gzip
import requests
import json
import re
import urllib.parse
import click


@click.command()
@click.option('--ago-user', required=True)
@click.option('--ago-password', required=True)
@click.option('--org-id', required=True)
@click.option('--target_dashboard_itemid', required=True)
@click.option('--expected-datasource-itemids', default=None, required=True,
              help='Pass one or multiple datasource ids, comma-separated')
@click.option('--new-datasource-itemid', default=None, required=False,
              help='New itemid for a dashboards datasources. \
                   Only supported if there is 1 datasource used in the dashboard')
@click.option('--dry-run', default=None, is_flag=True, required=False,
              help='Dry run. Dont update with modified code, just write to local files.')
def main(ago_user, ago_password, org_id, target_dashboard_itemid, expected_datasource_itemids, new_datasource_itemid, dry_run):
    """Takes a dashboard of {itemid}, gets it's JSON, finds field names and makes them lower-case,
    then posts it back to AGO.
    Optionally takes a new itemid for a new datasource, and updates it in-line as well. Likely of limited use
    since dashboards can have multiple datasources."""

    if not expected_datasource_itemids:
        raise AssertionError('No "expected_datasource_ids" var passed! You should know what data sources a dashboard \
        is using before attempting a large modification like this, Because if you dont update all the data sources to\
        have lower-case field names, it will break!')
    else:
        expected_datasource_itemids = expected_datasource_itemids.split(',')

    if new_datasource_itemid and len(expected_datasource_itemids) > 1:
        print('Not changing out datasource itemids since we expect there to be more than 1 in the dashboard.')
        new_datasource_itemid = None

    token_url = 'https://arcgis.com/sharing/rest/generateToken'
    data = {'username': ago_user,
            'password': ago_password,
            'referer': 'https://www.arcgis.com',
            'f': 'json'}
    ago_token = requests.post(token_url, data).json()['token']

    # Request the "data" json which contains field names and actual meat of the dashboard
    description_url = f'https://www.arcgis.com/sharing/rest/content/items/{target_dashboard_itemid}/description'
    params = {
        'f': 'json',
        'token': ago_token
    }
    response = requests.get(description_url, params=params)
    dashboard_title = response.json()["title"]
    print(f'\nOperating on dashboard: "{dashboard_title}"\n')

    # Request the "data" json which contains field names and actual meat of the dashboard
    data_url = f'https://www.arcgis.com/sharing/rest/content/items/{target_dashboard_itemid}/data'
    params = {
        'f': 'json',
        'token': ago_token
    }
    print(data_url)
    response = requests.get(data_url, params=params)
    #print(response.text)
    assert response.status_code == 200
    parsed_json = json.loads(response.text)
    #print(json.dumps(parsed_json, indent=2))

    # Write locally before modification
    f = open(f'./{target_dashboard_itemid}-ORIGINAL-dashboard.json', "w")
    # Write with indent so it's readable while I'm spot-checking
    f.write(json.dumps(parsed_json, indent=2))
    f.close()

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
                    if 'itemId' in json_obj["dataSource"].keys():
                        if json_obj["dataSource"]["type"] == 'itemDataSource':
                            found_datasource_itemids.add(json_obj["dataSource"]["itemId"])
                        if json_obj["dataSource"]["layerId"] == 0 and new_datasource_itemid:
                            json_obj["dataSource"]["itemId"] = new_datasource_itemid
                        elif json_obj["dataSource"]["layerId"] != 0 and new_datasource_itemid:
                            # Safety check for specific calls to layers within a dataSource that aren't simply 0
                            # If it's not using the first layer, which is 0, then fail out.
                            # We should not modify programmatically in this case.
                            raise Exception(f'''
                                    Found a specific layerId reference: {str(value)}!'
                                    Cannot update with new datasource itemId programmatically! Please make your itemId
                                    changes manually through assistant.esri-ps.com.
                                    ''')

                # Seems to be web-map specific but could be used in dashboards?
                if key == 'operationalLayers':
                    for i in json_obj["operationalLayers"]:
                        if i["layerType"] == 'ArcGISFeatureLayer':
                            found_datasource_itemids.add(i["itemId"])

                # if we have a field key, then the sub value is also a dict containing info about that field.
                # Edit: in some dashboards, it can apparently be a direct value
                if key == "field":
                    # If it's a dict, access the "name" key underneath it.
                    if type(json_obj["field"]) is dict:
                        field_name = json_obj["field"]["name"]
                        found_field_names.add(field_name.upper())
                        json_obj["field"]["name"] = field_name.lower()
                    # if it's a direct value instead of a dict, access value directly.
                    if type(json_obj["field"]) is str:
                        found_field_names.add(value.upper())
                        json_obj[key] = value.lower()

                # This has a direct field name value, lower-case if not empty
                if key == "fieldName":
                    if value:
                        found_field_names.add(value.upper())
                        json_obj[key] = value.lower()

                # This has a direct field name value, lower-case if not empty
                if key == "onStatisticField":
                    if value:
                        found_field_names.add(value.upper())
                        json_obj["onStatisticField"] = value.lower()
                # Also lower-case the new made statistic field name
                if key == "outStatisticFieldName":
                    if value:
                        # Don't add these to found_field_names because they're not a datasource field name
                        json_obj["outStatisticFieldName"] = value.lower()

                # This has a direct field name value, lower-case if not empty
                if key == "valueField":
                    # absoluteValue can sometimes be here, and is used by pie charts
                    if value and str(value) != 'absoluteValue':
                        found_field_names.add(value.upper())
                        json_obj[key] = value.lower()

                # fieldMap maps fields to another, which contain sourceName and targetName
                # Direct field name value in that case
                if key == "sourceName":
                    if value:
                        found_field_names.add(value.upper())
                        json_obj[key] = value.lower()
                if key == "targetName":
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
                        for f in found_field_names:
                            # Using regex, find all 'f' strings, and then substitute out a lower-case version
                            # ignore case otherwise several similar field names will result in inconsistent case.
                            # Also all we care about in "text" fields are field names surrounded by curly braces,
                            # so only search and replace for that
                            pattern = re.compile('{' + f + '}', re.IGNORECASE)
                            value = pattern.sub('{' + f.lower() + '}', value)
                            # Also look any values that begin with "{field/":
                            pattern = re.compile(r'{field/([^}]+)}', re.IGNORECASE)
                            value = pattern.sub(lambda match: '{field/' + match.group(1).lower() + '}', value)
                            json_obj[key] = value

                # pie-chart specific keys
                if key == 'x' or key == 'field1' or key == 'field2':
                    if value:
                        for f in found_field_names:
                            # Using regex, find all 'f' strings, and then substitute out a lower-case version
                            # ignore case otherwise several similar field names will result in inconsistent case.
                            pattern = re.compile(f, re.IGNORECASE)
                            value = pattern.sub(f.lower(), value)
                        json_obj[key] = value

                if key == 'expression':
                    # Use found_field_names set to replace field name strings with the lower_case version.
                    if value:
                        for f in found_field_names:
                            # Using regex, find all 'i' strings, and then substitute out a lower-case version
                            # ignore case otherwise several similar field names will result in inconsistent case.
                            pattern = re.compile(f, re.IGNORECASE)
                            value = pattern.sub(f.lower(), value)
                        json_obj[key] = value

                # Seems to be web-map specific but could be used in dashboards?
                if key == 'labelExpressionInfo':
                    sub_value = json_obj['labelExpressionInfo']['value']
                    # Using regex, find all 'i' strings, and then substitute out a lower-case version
                    # ignore case otherwise several similar field names will result in inconsistent case.
                    for f in found_field_names:
                        pattern = re.compile(f, re.IGNORECASE)
                        sub_value = pattern.sub(f.lower(), sub_value)
                    json_obj['labelExpressionInfo']['value'] = sub_value


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
                      'token': ago_token }
            print(f'\nSearching our datasource IDs with {search_url}')
            response = requests.get(search_url, params=params)

            if response.json()["results"][0]["type"] == 'Table' or response.json()["results"][0]["type"] == 'Feature Layer' or response.json()["results"][0]["type"] == 'Feature Service':
                # Loop through all layers we found, somehow esri is returning back multiple matches even when given a direct itemid
                for layer in response.json()["results"]:
                    #print(json.dumps(response.json(), indent=2))
                    # if we got multiple hits somehow (why esri), then confirm itemid matches
                    if layer["id"] == i:
                        dataset_name = layer["name"]
                        print(f"{i}'s name in AGO is: {layer['name']}")
                    else:
                        print(f'Ignoring bad match {layer["url"]}')
                        continue
                    # We can query for datasource json and get field names that way:
                    params = {'f': 'json',
                              'token': ago_token }
                    datasource_url = f'https://services.arcgis.com/{org_id}/ArcGIS/rest/services/{dataset_name}/FeatureServer/0'
                    print("\n" + datasource_url)
                    response2 = requests.get(datasource_url, params=params)
                    #print(json.dumps(response2.json(), indent=2))
                    for i in response2.json()['fields']:
                        field_name = i['name']
                        # Add to our found_field_names set for use in our 2nd run of find_and_modify_field_names()
                        found_field_names.add(field_name.upper())

    # first run, where we get datasource itemids and field names used in the dashboard json.
    find_and_modify_field_names(parsed_json)

    print(f'\nfound_datasource_itemids: {found_datasource_itemids}')
    if not found_datasource_itemids:
        raise AssertionError('No found datasources? If this dashboard has none it doesnt need this script!')
    # This is a safety measure in case we didn't account for all datasets informing a dashboard.
    print('Asserting our expected datasource ids are in the dashboard..')
    assert set(expected_datasource_itemids) == found_datasource_itemids
    gather_datasource_field_names()
    print(f'\nfound_field_names: {found_field_names}')

    # Run a second time after our found_field_names set is fully populated
    find_and_modify_field_names(parsed_json)


    # Write locally after modification
    f = open(f'./{target_dashboard_itemid}-MODIFIED-dashboard.json', "w")
    # Write with indent so it's readable while I'm spot-checking
    f.write(json.dumps(parsed_json, indent=2))
    f.close()

    if dry_run:
        print('\nDry run flag passed, not updating...')
    else:
        print('\nNow attempting to update the dashboard with our modified json..')
        # Once we have our updated json, update the dashboard with it
        regular_json = json.dumps(parsed_json)
        #encoded_json = urllib.parse.quote(json.dumps(parsed_json))
        #compressed_data = gzip.compress(json.dumps(parsed_json).encode('utf-8'))

        form_data = {
            'f': 'json',
            'id': target_dashboard_itemid,
            'token': ago_token,
            'text': regular_json
        }
        # Seems to be necessary to encode it all, otherwise we get an error about our URI being too long
        # since the entire json contents are passed in the URL, encoding makes it more compact I believe?
        encoded_form_data = urllib.parse.urlencode(form_data)

        update_url = f'https://www.arcgis.com/sharing/rest/content/users/maps.phl.data/items/{target_dashboard_itemid}/update'
        print(update_url)

        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = requests.post(update_url, headers=headers, data=encoded_form_data)
        print(response.text)
        assert response.status_code == 200
    print('Done.')


if __name__ == '__main__':
    main()
