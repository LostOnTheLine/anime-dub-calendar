from flask import Flask, render_template_string
import yaml

app = Flask(__name__)

@app.route('/')
def home():
    try:
        with open("/data/metadata.yaml", "r") as f:
            metadata = yaml.safe_load(f) or {}
    except FileNotFoundError:
        metadata = {}
    
    html = """
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