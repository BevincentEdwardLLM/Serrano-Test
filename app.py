from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import io
import os
import shutil
from src.model import openai_model_with_mcp_tools
from src.reentry_care_plan import generate_reentry_care_plan, get_candidates_by_name, generate_data_validation_report
from src.reentry_care_plan import read_cloud_sql, read_bigquery, normalize_columns
from dotenv import load_dotenv
import pandas as pd
import re

# Load environment variables
load_dotenv()

# Create Flask app with static folder for frontend
app = Flask(__name__, static_folder='frontend', static_url_path='')
CORS(app)

# Serve frontend files
@app.route('/')
def serve_frontend():
    """Serve the main HTML file"""
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/app.js')
def serve_js():
    """Serve the JavaScript file"""
    return send_from_directory(app.static_folder, 'app.js')

# Serve image files
@app.route('/image/<path:filename>')
def serve_images(filename):
    """Serve images from the image directory"""
    try:
        return send_from_directory('image', filename)
    except FileNotFoundError:
        return jsonify({'error': 'Image not found'}), 404

# Health check endpoint
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'message': 'Backend is running'})

# Helper function to get merged data from all sources
def get_merged_data(name, medical_id):
    """
    Retrieves and merges a single candidate's data from all sources.
    Returns a dictionary of the merged data.
    """
    try:
        file_data = pd.read_excel("ExcelFiles/reentry5.xlsx")
        file_data = normalize_columns(file_data)
        
        if "Medical ID Number" in file_data.columns:
            excel_row = file_data[file_data["Medical ID Number"].astype(str) == medical_id]
            excel_dict = excel_row.to_dict(orient="records")[0] if not excel_row.empty else {}
        else:
            excel_dict = {}
        
        sql_record = read_cloud_sql(name, medical_id)
        sql_record = normalize_columns(sql_record)
        sql_dict = sql_record.to_dict(orient="records")[0] if not sql_record.empty else {}

        bq_record = read_bigquery(name, medical_id)
        bq_record = normalize_columns(bq_record)
        bq_dict = bq_record.to_dict(orient="records")[0] if not bq_record.empty else {}

        merged_dict = {**excel_dict, **sql_dict, **bq_dict}
        return merged_dict
    except Exception as e:
        print(f"Error retrieving merged data for candidate: {e}")
        return {}

# Get candidates by name endpoint
@app.route('/get_candidates_by_name', methods=['POST'])
def get_candidates_endpoint():
    """Get all candidate profiles for a given name"""
    print("\n=== GET_CANDIDATES_BY_NAME ENDPOINT ===")
    try:
        data = request.get_json()
        print(f"📥 INPUT: {data}")
        candidate_name = data.get('candidate_name', '').strip()

        if not candidate_name:
            print("❌ ERROR: No candidate name provided")
            return jsonify({'error': 'Candidate name is required'}), 400

        print(f"🔍 SEARCHING for candidates with name: '{candidate_name}'")

        print("🔧 CALLING get_candidates_by_name()...")
        candidates = get_candidates_by_name(candidate_name)
        print(f"📊 FOUND {len(candidates)} candidates: {candidates}")

        profiles = []
        for name, medical_id in candidates:
            merged_data = get_merged_data(name, medical_id)
            address = merged_data.get("Residential Address", "N/A")
            phone_number = merged_data.get("Telephone", "N/A")

            display_text = f"{name} (Medical ID: {medical_id}) - Residential Address: {address} - Telephone Number: {phone_number}"

            profiles.append({
                'name': name,
                'medical_id': medical_id,
                'display_text': display_text
            })

        result = {
            'success': True,
            'candidates': profiles,
            'count': len(profiles)
        }
        print(f"📤 OUTPUT: {result}")
        return jsonify(result)

    except Exception as e:
        print(f"❌ ERROR in get_candidates_endpoint: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        print("=== END GET_CANDIDATES_BY_NAME ===")


# Reentry Care Plan endpoint
@app.route('/generate_reentry_care_plan', methods=['POST'])
def generate_reentry_endpoint():
    """Handle Reentry Care Plan generation"""
    print("\n=== GENERATE_REENTRY_CARE_PLAN ENDPOINT ===")
    try:
        data = request.get_json()
        print(f"📥 INPUT: {data}")
        selected_fields = data.get('selected_fields', [])
        candidate_name = data.get('candidate_name', '')
        app_option = data.get('app_option', 'reentry_care_plan')

        if not candidate_name:
            print("❌ ERROR: No candidate name provided")
            return jsonify({'error': 'Candidate name is required'}), 400

        if not selected_fields:
            print("❌ ERROR: No fields selected")
            return jsonify({'error': 'At least one field must be selected'}), 400

        print(f"🏗️ GENERATING Reentry Care Plan for '{candidate_name}'")
        print(f"📋 SELECTED FIELDS ({len(selected_fields)}): {selected_fields}")

        print("🔧 CALLING generate_reentry_care_plan()...")
        doc_io = generate_reentry_care_plan(selected_fields, candidate_name, app_option)

        if doc_io is None:
            print("❌ ERROR: Document generation failed")
            return jsonify({'error': 'Failed to generate care plan'}), 500

        print("📄 DOCUMENT generated successfully")

        output_path = "data/reentry_output.docx"
        with open(output_path, 'wb') as f:
            f.write(doc_io.getvalue())

        filename = f"{candidate_name}_reentry_care_plan.docx"
        print(f"📤 SENDING FILE: {filename}")
        return send_file(
            output_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

    except Exception as e:
        print(f"❌ ERROR in reentry endpoint: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        print("=== END GENERATE_REENTRY_CARE_PLAN ===")


# Data Validation Report endpoint
@app.route('/generate_data_validation_report', methods=['POST'])
def generate_validation_endpoint():
    """Handle Data Validation Report generation"""
    print("\n=== GENERATE_DATA_VALIDATION_REPORT ENDPOINT ===")
    try:
        data = request.get_json()
        print(f"📥 INPUT: {data}")
        selected_fields = data.get('selected_fields', [])
        candidate_name = data.get('candidate_name', '')
        app_option = data.get('app_option', 'data_validation_report')

        if not candidate_name:
            print("❌ ERROR: No candidate name provided")
            return jsonify({'error': 'Candidate name is required'}), 400

        if not selected_fields:
            print("❌ ERROR: No fields selected")
            return jsonify({'error': 'At least one field must be selected'}), 400

        print(f"🏗️ GENERATING Data Validation Report for '{candidate_name}'")
        print(f"📋 SELECTED FIELDS ({len(selected_fields)}): {selected_fields}")

        print("🔧 CALLING generate_data_validation_report()...")
        doc_io = generate_data_validation_report(selected_fields, candidate_name, app_option)

        if doc_io is None:
            print("❌ ERROR: Document generation failed")
            return jsonify({'error': 'Failed to generate validation report'}), 500

        print("📄 DOCUMENT generated successfully")

        output_path = "data/validation_output.docx"
        with open(output_path, 'wb') as f:
            f.write(doc_io.getvalue())
        
        filename = f"{candidate_name}_data_validation_report.docx"
        print(f"📤 SENDING FILE: {filename}")
        return send_file(
            output_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )

    except Exception as e:
        print(f"❌ ERROR in validation endpoint: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        print("=== END GENERATE_DATA_VALIDATION_REPORT ===")


# Adult Health Risk Assessment endpoint
@app.route('/generate_hra_adult', methods=['POST'])
def generate_hra_adult_endpoint():
    """Handle Adult HRA generation using OpenAI MCP tools"""
    try:
        data = request.get_json()
        selected_fields = data.get('selected_fields', [])
        candidate_name = data.get('candidate_name', '')

        if not candidate_name:
            return jsonify({'error': 'Candidate name is required'}), 400

        if not selected_fields:
            return jsonify({'error': 'At least one field must be selected'}), 400

        print(f"Generating Adult HRA for {candidate_name} with fields: {selected_fields}")

        result = openai_model_with_mcp_tools(selected_fields, candidate_name)

        if isinstance(result, dict):
            output_path = "data/output.docx"
            if not os.path.exists(output_path):
                return jsonify({'error': 'Document generation failed - output file not created'}), 500

            final_path = f"data/{candidate_name}_adult_hra.docx"
            shutil.copy(output_path, final_path)

            return send_file(
                final_path,
                as_attachment=True,
                download_name=f"{candidate_name}_adult_hra.docx",
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        else:
            return jsonify({'error': f'Failed to generate HRA: {result}'}), 500

    except Exception as e:
        print(f"Error in adult HRA endpoint: {e}")
        return jsonify({'error': str(e)}), 500

# Juvenile Health Risk Assessment endpoint
@app.route('/generate_hra_juvenile', methods=['POST'])
def generate_hra_juvenile_endpoint():
    """Handle Juvenile HRA generation using OpenAI MCP tools"""
    try:
        data = request.get_json()
        selected_fields = data.get('selected_fields', [])
        candidate_name = data.get('candidate_name', '')

        if not candidate_name:
            return jsonify({'error': 'Candidate name is required'}), 400

        if not selected_fields:
            return jsonify({'error': 'At least one field must be selected'}), 400

        print(f"Generating Juvenile HRA for {candidate_name} with fields: {selected_fields}")

        result = openai_model_with_mcp_tools(selected_fields, candidate_name)

        if isinstance(result, dict):
            output_path = "data/output.docx"
            if not os.path.exists(output_path):
                return jsonify({'error': 'Document generation failed - output file not created'}), 500

            final_path = f"data/{candidate_name}_juvenile_hra.docx"
            shutil.copy(output_path, final_path)

            return send_file(
                final_path,
                as_attachment=True,
                download_name=f"{candidate_name}_juvenile_hra.docx",
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        else:
            return jsonify({'error': f'Failed to generate HRA: {result}'}), 500

    except Exception as e:
        print(f"Error in juvenile HRA endpoint: {e}")
        return jsonify({'error': str(e)}), 500

# Error handlers
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors by serving the frontend"""
    return send_from_directory(app.static_folder, 'index.html')

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    os.makedirs('image', exist_ok=True)
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)