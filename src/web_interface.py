from flask import Flask, render_template_string, send_file
import yaml
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

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

@app.route('/')
def home():
    try:
        with open("/data/metadata.yaml", "r") as f:
            metadata = yaml.safe_load(f) or {}
    except FileNotFoundError:
        metadata = {}
    
    html = """
    <head>
        <link rel="icon" type="image/x-icon" href="/favicon.ico">
        <title>Anime Dub Calendar</title>
    </head>
    <h1>Anime Dub Metadata</h1>
    <table border="1">
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
    """
    return render_template_string(html, metadata=metadata)

def run_web_app():
    app.run(host="0.0.0.0", port=5000)