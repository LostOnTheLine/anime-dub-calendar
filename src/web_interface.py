from flask import Flask, request, render_template_string, send_file, redirect, url_for
import yaml
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from utils import parse_show_page, save_parsed_entry, remove_parsed_entry
import os  # Added this import

app = Flask(__name__)
REPO_DIR = "/app/repo"

def generate_favicon():
    img = Image.new('RGB', (32, 32), color='white')
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except:
        font = ImageFont.load_default()
    d.text((4, 8), "Dub", font=font, fill='black')
    buffer = BytesIO()
    img.save(buffer, format="ICO")
    buffer.seek(0)
    return buffer

@app.route('/favicon.ico')
def favicon():
    return send_file(generate_favicon(), mimetype='image/x-icon')

@app.route('/', methods=["GET", "POST"])
def home():
    try:
        with open(os.path.join(REPO_DIR, "metadata.yaml"), "r") as f:
            metadata = yaml.safe_load(f) or {}
    except FileNotFoundError:
        metadata = {}

    parsed_file = os.path.join(REPO_DIR, "parsed_data.yaml")
    parsed_entries = {}
    if os.path.exists(parsed_file):
        with open(parsed_file, "r") as f:
            parsed_entries = yaml.safe_load(f) or {}

    html = """
    <head>
        <link rel="icon" type="image/x-icon" href="/favicon.ico">
        <title>Anime Dub Calendar</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid black; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
            .entry { margin: 10px 0; padding: 10px; border: 1px solid #ccc; }
            .error { color: red; }
        </style>
    </head>
    <body>
        <h1>Anime Dub Metadata</h1>
        
        <h2>Manually Add Show</h2>
        <form method="POST" action="{{ url_for('manual_add') }}">
            <label>MAL ID or URL:</label><br>
            <input type="text" name="identifier" placeholder="e.g., 12345 or https://myanimelist.net/anime/12345" required><br><br>
            <input type="submit" value="Fetch Metadata">
        </form>
        {% if fetched_metadata %}
            <h3>Fetched Metadata</h3>
            <div class="entry">
                {% for key, value in fetched_metadata.items() %}
                    <p><strong>{{ key }}:</strong> {{ value }}</p>
                {% endfor %}
                <form method="POST" action="{{ url_for('save_manual') }}">
                    <input type="hidden" name="mal_id" value="{{ fetched_metadata['MAL_ID'] }}">
                    <input type="hidden" name="metadata" value="{{ fetched_metadata | tojson }}">
                    <label><input type="checkbox" name="save_parser" checked> Save for parser?</label><br><br>
                    <input type="submit" value="Save Metadata">
                </form>
            </div>
        {% endif %}
        {% if error %}
            <p class="error">{{ error }}</p>
        {% endif %}

        <h2>Current Metadata</h2>
        <table>
            <tr>
                <th>MAL ID</th>
                <th>Show Name</th>
                <th>Air Day</th>
                <th>Latest Episode</th>
                <th>Total Episodes</th>
                <th>Streaming</th>
            </tr>
            {% for mal_id, data in metadata.items() %}
            <tr>
                <td>{{ mal_id }}</td>
                <td>{{ data.ShowName }}</td>
                <td>{{ data.AirDay }}</td>
                <td>{{ data.LatestEpisode }}</td>
                <td>{{ data.TotalEpisodes or '?' }}</td>
                <td>{{ data.Streaming or 'Not Listed' }}</td>
            </tr>
            {% endfor %}
        </table>

        <h2>Parsed Data</h2>
        {% if parsed_entries %}
            {% for mal_id, data in parsed_entries.items() %}
                <div class="entry">
                    <p><strong>MAL ID:</strong> {{ mal_id }}</p>
                    <p><strong>Show Name:</strong> {{ data['ShowName'] }}</p>
                    <p><strong>Auto Remove After:</strong> {{ data.get('auto_remove_after_days', 180) }} days</p>
                    <form method="POST" action="{{ url_for('remove_manual') }}">
                        <input type="hidden" name="mal_id" value="{{ mal_id }}">
                        <input type="submit" value="Remove" onclick="return confirm('Are you sure?');">
                    </form>
                </div>
            {% endfor %}
        {% else %}
            <p>No parsed data found.</p>
        {% endif %}
    </body>
    """
    return render_template_string(html, metadata=metadata, parsed_entries=parsed_entries, fetched_metadata=app.config.get('fetched_metadata'), error=app.config.get('error'))

@app.route("/manual_add", methods=["POST"])
def manual_add():
    identifier = request.form.get("identifier")
    if not identifier:
        app.config['error'] = "Please provide a MAL ID or URL"
        app.config['fetched_metadata'] = None
        return redirect(url_for('home'))

    if "myanimelist.net/anime/" in identifier:
        try:
            mal_id = identifier.split("/anime/")[1].split("/")[0]
            url = identifier
        except IndexError:
            app.config['error'] = "Invalid URL format"
            app.config['fetched_metadata'] = None
            return redirect(url_for('home'))
    else:
        try:
            mal_id = int(identifier)
            url = f"https://myanimelist.net/anime/{mal_id}"
        except ValueError:
            app.config['error'] = "Invalid MAL ID"
            app.config['fetched_metadata'] = None
            return redirect(url_for('home'))

    metadata = parse_show_page(url)
    if not metadata:
        app.config['error'] = "Failed to fetch metadata"
        app.config['fetched_metadata'] = None
    else:
        metadata["MAL_ID"] = str(mal_id)
        app.config['fetched_metadata'] = metadata
        app.config['error'] = None
    return redirect(url_for('home'))

@app.route("/save_manual", methods=["POST"])
def save_manual():
    mal_id = request.form.get("mal_id")
    metadata = yaml.safe_load(request.form.get("metadata"))
    save_parser = request.form.get("save_parser") == "on"

    if save_parser:
        save_parsed_entry(mal_id, metadata)
    app.config['fetched_metadata'] = None
    app.config['error'] = None
    return redirect(url_for('home'))

@app.route("/remove_manual", methods=["POST"])
def remove_manual():
    mal_id = request.form.get("mal_id")
    remove_parsed_entry(mal_id)
    app.config['fetched_metadata'] = None
    app.config['error'] = None
    return redirect(url_for('home'))

def run_web_app():
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    run_web_app()