from flask import Flask, render_template, request, jsonify
import json
import shlex
from urllib.parse import urlparse, parse_qs
from collections import defaultdict

app = Flask(__name__)

# ----------------- cURL Helpers -----------------
def parse_curl(curl_command):
    details = {'method': 'GET', 'url': None, 'headers': {}, 'body': None}
    command_parts = shlex.split(curl_command)
    i = 0
    while i < len(command_parts):
        part = command_parts[i]
        if part in ('-X', '--request') and i + 1 < len(command_parts):
            details['method'] = command_parts[i+1].upper()
            i += 2
        elif part in ('-H', '--header') and i + 1 < len(command_parts):
            header_parts = command_parts[i+1].split(':', 1)
            if len(header_parts) == 2:
                key, value = header_parts
                details['headers'][key.strip()] = value.strip()
            i += 2
        elif part in ('-d', '--data', '--data-raw', '--data-binary') and i + 1 < len(command_parts):
            body_content = command_parts[i+1]
            try:
                details['body'] = json.loads(body_content)
            except json.JSONDecodeError:
                details['body'] = body_content
            i += 2
        elif part in ('-F', '--form') and i + 1 < len(command_parts):
            details['body'] = details.get('body', {})
            form_data = command_parts[i+1].split('=', 1)
            if len(form_data) == 2:
                key, value = form_data
                details['body'][key] = value
            i += 2
        elif part.startswith('http'):
            details['url'] = part
            i += 1
        else:
            i += 1
    return details

def infer_json_schema(data):
    if isinstance(data, dict):
        return {"type": "object", "properties": {k: infer_json_schema(v) for k, v in data.items()}}
    elif isinstance(data, list):
        return {"type": "array", "items": infer_json_schema(data[0]) if data else {}}
    elif isinstance(data, str):
        return {"type": "string"}
    elif isinstance(data, int):
        return {"type": "integer"}
    elif isinstance(data, float):
        return {"type": "number"}
    elif isinstance(data, bool):
        return {"type": "boolean"}
    else:
        return {"type": "object"}

def generate_openapi_json(requests):
    openapi_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Generated API Specification", "version": "1.0.0"},
        "servers": [],
        "paths": defaultdict(dict),
        "components": {"schemas": {}, "securitySchemes": {}}
    }
    unique_servers = set()

    for i, req in enumerate(requests):
        if not req.strip():
            continue
        parsed_data = parse_curl(req)
        if not parsed_data['url']:
            continue

        url_parts = urlparse(parsed_data['url'])
        server_url = f"{url_parts.scheme}://{url_parts.netloc}"
        if server_url not in unique_servers:
            openapi_spec['servers'].append({"url": server_url})
            unique_servers.add(server_url)

        path = url_parts.path or "/"
        method = parsed_data['method'].lower()
        body_content = parsed_data['body']
        headers = parsed_data.get('headers', {})

        operation_id = f"{method}_{path.replace('/', '_').strip('_') or 'root'}_{i}"
        path_details = {
            "summary": f"{parsed_data['method']} {path}",
            "operationId": operation_id,
            "servers": [{"url": server_url}],
            "responses": {"200": {"description": "Successful response"}}
        }

        # query params
        query_params = parse_qs(url_parts.query)
        if query_params:
            path_details["parameters"] = []
            for key, values in query_params.items():
                path_details["parameters"].append({
                    "name": key, "in": "query", "required": False,
                    "schema": {"type": "string"}, "example": values[0]
                })

        # headers
        for header, value in headers.items():
            if header.lower() not in ['content-type', 'authorization']:
                path_details.setdefault("parameters", []).append({
                    "name": header, "in": "header", "required": False,
                    "schema": {"type": "string"}, "example": value
                })

        # auth
        auth_header = headers.get('Authorization')
        if auth_header:
            if auth_header.lower().startswith('bearer '):
                openapi_spec['components']['securitySchemes']['BearerAuth'] = {"type": "http", "scheme": "bearer"}
                path_details['security'] = [{"BearerAuth": []}]
            elif auth_header.lower().startswith('basic '):
                openapi_spec['components']['securitySchemes']['BasicAuth'] = {"type": "http", "scheme": "basic"}
                path_details['security'] = [{"BasicAuth": []}]

        # body
        if body_content:
            schema_name = f"Schema_{operation_id}"
            content_type = parsed_data['headers'].get('Content-Type', 'application/json')
            path_details["requestBody"] = {
                "required": True,
                "content": {content_type: {"schema": {}}}
            }
            if content_type == 'application/json' and isinstance(body_content, dict):
                body_schema = infer_json_schema(body_content)
                openapi_spec['components']['schemas'][schema_name] = body_schema
                path_details["requestBody"]["content"][content_type]["schema"]["$ref"] = f"#/components/schemas/{schema_name}"
            else:
                path_details["requestBody"]["content"][content_type]["schema"] = {"type": "string"}

        openapi_spec['paths'][path][method] = path_details

    return openapi_spec

# ----------------- Routes -----------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/validate_curl', methods=['POST'])
def validate_curl():
    data = request.get_json(force=True)
    curl_command = data.get('command', '')
    if not curl_command:
        return jsonify({"error": "No cURL command provided"}), 400
    parsed_data = parse_curl(curl_command)
    if not parsed_data.get('url'):
        return jsonify({"error": "URL not found"}), 400
    return jsonify({"message": "cURL command is valid!"})

@app.route('/generate_openapi', methods=['POST'])
def generate():
    data = request.get_json(force=True)
    requests_list = data.get('requests', [])
    if not isinstance(requests_list, list):
        return jsonify({"error": "Input must be a list"}), 400
    return jsonify(generate_openapi_json(requests_list))

@app.route('/upload_curl_file', methods=['POST'])
def upload_curl_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files['file']
    file_content = file.read().decode('utf-8')
    requests_list = [line.strip() for line in file_content.splitlines() if line.strip()]
    return jsonify(generate_openapi_json(requests_list))

@app.route('/convert_postman_json', methods=['POST'])
def convert_postman_json():
    return jsonify({"message": "Postman to NeoLoad conversion not implemented in this demo"})

@app.route('/postman_to_openapi', methods=['POST'])
def postman_to_openapi():
    try:
        data = request.get_json(force=True)
        collection = data.get('collection', {})

        if not collection:
            return jsonify({"error": "Invalid or empty Postman collection"}), 400

        openapi_spec = {
            "openapi": "3.0.0",
            "info": {
                "title": collection.get("info", {}).get("name", "Converted Postman Collection"),
                "version": collection.get("info", {}).get("version", "1.0.0")
            },
            "servers": [],
            "paths": {},
            "components": {"schemas": {}}
        }

        for idx, item in enumerate(collection.get("item", [])):
            request_data = item.get("request", {})
            if not request_data:
                continue

            # URL & path
            url_info = request_data.get("url", {})
            raw_url, path, query_params = "", "/", []
            if isinstance(url_info, dict):
                raw_url = url_info.get("raw", "")
                path = "/" + "/".join(url_info.get("path", []))
                query_params = url_info.get("query", [])
            else:
                raw_url = str(url_info)

            method = request_data.get("method", "GET").lower()
            summary = item.get("name", f"Request {idx+1}")

            # Add server (from raw_url if not already present)
            if raw_url:
                parsed_url = urlparse(raw_url)
                server_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                if server_url and server_url not in [s["url"] for s in openapi_spec["servers"]]:
                    openapi_spec["servers"].append({"url": server_url})

            # Build operation
            operation = {
                "summary": summary,
                "responses": {"200": {"description": "Successful response"}}
            }

            # Query params
            if query_params:
                operation["parameters"] = []
                for q in query_params:
                    operation["parameters"].append({
                        "name": q.get("key", ""),
                        "in": "query",
                        "required": not q.get("disabled", False),
                        "schema": {"type": "string"},
                        "example": q.get("value", "")
                    })

            # Headers
            headers = request_data.get("header", [])
            for h in headers:
                if h.get("key") and h.get("key").lower() not in ["content-type", "authorization"]:
                    operation.setdefault("parameters", []).append({
                        "name": h["key"],
                        "in": "header",
                        "required": False,
                        "schema": {"type": "string"},
                        "example": h.get("value", "")
                    })

            # Body
            body = request_data.get("body", {})
            if body and body.get("mode") == "raw":
                try:
                    parsed_json = json.loads(body.get("raw", ""))
                    schema = infer_json_schema(parsed_json)
                    schema_name = f"Schema_{method}_{idx}"
                    openapi_spec["components"]["schemas"][schema_name] = schema
                    operation["requestBody"] = {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{schema_name}"}
                            }
                        }
                    }
                except Exception:
                    operation["requestBody"] = {
                        "required": True,
                        "content": {"text/plain": {"schema": {"type": "string"}}}
                    }

            openapi_spec["paths"].setdefault(path, {})[method] = operation

        return jsonify(openapi_spec)
    except Exception as e:
        return jsonify({"error": f"Failed to convert Postman: {e}"}), 500

if __name__ == '__main__':
    app.run(debug=True)
