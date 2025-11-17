"""
Configuration Validation Script

This script validates all required configuration and credentials
before running the transcription workflow. Run this first to ensure
everything is properly set up.
"""

import os
import sys


def print_status(test_name, success, message=""):
    """Print test status with colored output"""
    status = "✓" if success else "✗"
    color = "\033[92m" if success else "\033[91m"
    reset = "\033[0m"
    print(f"{color}{status}{reset} {test_name}", end="")
    if message:
        print(f": {message}")
    else:
        print()
    return success


def test_python_version():
    """Check Python version"""
    version = sys.version_info
    success = version.major == 3 and version.minor >= 7
    return print_status(
        "Python version",
        success,
        f"Python {version.major}.{version.minor}.{version.micro}" + 
        ("" if success else " (requires Python 3.7+)")
    )


def test_package_imports():
    """Test if required packages can be imported"""
    packages = {
        "requests": "HTTP client library",
        "pyodbc": "SQL Server driver",
        "azure.storage.blob": "Azure Blob Storage client"
    }
    
    all_success = True
    for package, description in packages.items():
        try:
            __import__(package)
            print_status(f"Package: {package}", True, description)
        except ImportError:
            print_status(f"Package: {package}", False, f"NOT INSTALLED - {description}")
            all_success = False
    
    return all_success


def test_odbc_drivers():
    """Check available ODBC drivers"""
    try:
        import pyodbc
        drivers = pyodbc.drivers()
        
        if not drivers:
            print_status("ODBC drivers", False, "No ODBC drivers found")
            return False
        
        sql_server_drivers = [d for d in drivers if "SQL Server" in d]
        if sql_server_drivers:
            print_status("ODBC drivers", True, f"Found: {', '.join(sql_server_drivers)}")
            return True
        else:
            print_status("ODBC drivers", False, f"No SQL Server drivers. Available: {', '.join(drivers)}")
            return False
    except ImportError:
        print_status("ODBC drivers", False, "pyodbc not installed")
        return False


def test_environment_variables():
    """Check if environment variables are set"""
    required_vars = {
        "VOICEGAIN_TOKEN": "VoiceGain API bearer token",
        "SQL_CONNECTION_STRING": "SQL Server connection string",
        "BLOB_CONNECTION_STRING": "Azure Blob Storage connection string",
        "SAS_TOKEN": "SAS token for audio file access"
    }
    
    optional_vars = {
        "AZURE_FUNCTION_URL": "Azure Function URL (optional)",
        "COMPANY_GUID": "Company GUID (can be passed as parameter)",
        "EVALUATION_DATE": "Evaluation date (can be passed as parameter)"
    }
    
    all_success = True
    
    print("\n📋 Required Environment Variables:")
    for var, description in required_vars.items():
        value = os.getenv(var)
        if value:
            masked = value[:10] + "..." if len(value) > 10 else value
            print_status(var, True, f"{description} (set: {masked})")
        else:
            print_status(var, False, f"{description} - NOT SET")
            all_success = False
    
    print("\n📋 Optional Environment Variables:")
    for var, description in optional_vars.items():
        value = os.getenv(var)
        if value:
            masked = value[:20] + "..." if len(value) > 20 else value
            print_status(var, True, f"{description} (set: {masked})")
        else:
            print_status(var, True, f"{description} - not set (optional)")
    
    return all_success


def test_sql_connection():
    """Test SQL Server connectivity"""
    connection_string = os.getenv("SQL_CONNECTION_STRING")
    
    if not connection_string:
        print_status("SQL connection", False, "No connection string configured")
        return False
    
    try:
        import pyodbc
        conn = pyodbc.connect(connection_string, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        conn.close()
        print_status("SQL connection", True, "Successfully connected")
        return True
    except ImportError:
        print_status("SQL connection", False, "pyodbc not installed")
        return False
    except Exception as e:
        print_status("SQL connection", False, f"Connection failed: {str(e)[:60]}")
        return False


def test_blob_storage():
    """Test Azure Blob Storage connectivity"""
    connection_string = os.getenv("BLOB_CONNECTION_STRING")
    
    if not connection_string:
        print_status("Blob storage", False, "No connection string configured")
        return False
    
    try:
        from azure.storage.blob import BlobServiceClient
        client = BlobServiceClient.from_connection_string(connection_string)
        # Try to list containers (lightweight operation)
        list(client.list_containers(max_results=1))
        print_status("Blob storage", True, "Successfully connected")
        return True
    except ImportError:
        print_status("Blob storage", False, "azure-storage-blob not installed")
        return False
    except Exception as e:
        print_status("Blob storage", False, f"Connection failed: {str(e)[:60]}")
        return False


def test_voicegain_api():
    """Test VoiceGain API connectivity"""
    token = os.getenv("VOICEGAIN_TOKEN")
    
    if not token:
        print_status("VoiceGain API", False, "No token configured")
        return False
    
    try:
        import requests
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(
            "https://api.voicegain.ai/v1/asr/transcribe",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            print_status("VoiceGain API", True, "Authentication successful")
            return True
        elif response.status_code == 401:
            print_status("VoiceGain API", False, "Invalid token (401 Unauthorized)")
            return False
        else:
            print_status("VoiceGain API", False, f"Unexpected status: {response.status_code}")
            return False
    except ImportError:
        print_status("VoiceGain API", False, "requests not installed")
        return False
    except Exception as e:
        print_status("VoiceGain API", False, f"Connection failed: {str(e)[:60]}")
        return False


def test_azure_function():
    """Test Azure Function connectivity (optional)"""
    function_url = os.getenv("AZURE_FUNCTION_URL")
    
    if not function_url:
        print_status("Azure Function", True, "Not configured (will use local formatting)")
        return True
    
    try:
        import requests
        # Try a simple GET request (most Azure Functions respond to GET)
        response = requests.get(function_url, timeout=10)
        
        # Accept any response that's not a connection error
        print_status("Azure Function", True, f"Reachable (status: {response.status_code})")
        return True
    except ImportError:
        print_status("Azure Function", False, "requests not installed")
        return False
    except Exception as e:
        print_status("Azure Function", False, f"Not reachable: {str(e)[:60]}")
        return False


def main():
    """Run all validation tests"""
    print("="*70)
    print("🔍 Transcription Workflow - Configuration Validation")
    print("="*70)
    
    print("\n📦 System Requirements:")
    results = []
    results.append(test_python_version())
    results.append(test_package_imports())
    results.append(test_odbc_drivers())
    
    print("\n🔑 Configuration:")
    results.append(test_environment_variables())
    
    print("\n🔌 Connectivity Tests:")
    results.append(test_sql_connection())
    results.append(test_blob_storage())
    results.append(test_voicegain_api())
    test_azure_function()  # Optional, don't include in results
    
    print("\n" + "="*70)
    
    if all(results):
        print("✅ All validations passed! You're ready to run the workflow.")
        print("\nRun the workflow with:")
        print("  python transcription_workflow.py")
        return 0
    else:
        print("❌ Some validations failed. Please fix the issues above.")
        print("\nFor help, see:")
        print("  - TRANSCRIPTION_WORKFLOW_README.md")
        print("  - transcription.env.example")
        print("  - requirements_transcription.txt")
        return 1


if __name__ == "__main__":
    sys.exit(main())

