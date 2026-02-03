"""
VentureLab Google Ads MCP Connector - Streamlit UI
A web interface to interact with the Google Ads MCP server.
"""

import streamlit as st
import requests
import pandas as pd
import json

# Page config
st.set_page_config(
    page_title="VentureLab Google Ads",
    page_icon="📊",
    layout="wide"
)

# Common Google Ads resources and their typical fields
RESOURCE_FIELDS = {
    "campaign": [
        "campaign.id",
        "campaign.name",
        "campaign.status",
        "campaign.advertising_channel_type",
        "campaign.start_date",
        "campaign.end_date",
        "campaign.budget_amount_micros",
    ],
    "ad_group": [
        "ad_group.id",
        "ad_group.name",
        "ad_group.status",
        "ad_group.type",
        "campaign.id",
        "campaign.name",
    ],
    "ad_group_ad": [
        "ad_group_ad.ad.id",
        "ad_group_ad.ad.name",
        "ad_group_ad.status",
        "ad_group_ad.ad.type",
        "ad_group.id",
        "ad_group.name",
        "campaign.id",
    ],
    "keyword_view": [
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
        "ad_group_criterion.status",
        "ad_group.name",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
    ],
    "campaign_budget": [
        "campaign_budget.id",
        "campaign_budget.name",
        "campaign_budget.amount_micros",
        "campaign_budget.status",
        "campaign_budget.delivery_method",
    ],
    "customer": [
        "customer.id",
        "customer.descriptive_name",
        "customer.currency_code",
        "customer.time_zone",
    ],
    "metrics (campaign level)": [
        "campaign.id",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
        "metrics.ctr",
        "metrics.average_cpc",
    ],
}


def init_session_state():
    """Initialize session state variables."""
    if "api_url" not in st.session_state:
        st.session_state.api_url = ""
    if "api_token" not in st.session_state:
        st.session_state.api_token = ""
    if "connected" not in st.session_state:
        st.session_state.connected = False
    if "account_info" not in st.session_state:
        st.session_state.account_info = None
    if "last_result" not in st.session_state:
        st.session_state.last_result = None


def make_request(endpoint: str, method: str = "GET", data: dict = None, expect_json: bool = True) -> dict:
    """Make an authenticated request to the API."""
    url = f"{st.session_state.api_url.rstrip('/')}{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": st.session_state.api_token,
    }

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        else:
            response = requests.post(url, headers=headers, json=data, timeout=60)

        response.raise_for_status()

        # Handle non-JSON responses (like /healthz which returns plain text)
        if not expect_json:
            return {"success": True, "data": response.text}

        try:
            return {"success": True, "data": response.json()}
        except requests.exceptions.JSONDecodeError:
            # Response is not JSON, return as text
            return {"success": True, "data": response.text}
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        if hasattr(e, "response") and e.response is not None:
            try:
                error_data = e.response.json()
                error_msg = error_data.get("error", str(e))
            except:
                error_msg = e.response.text or str(e)
        return {"success": False, "error": error_msg}


def test_connection():
    """Test the API connection."""
    result = make_request("/healthz", expect_json=False)
    if result["success"]:
        # Also fetch account info
        info_result = make_request("/api/info")
        if info_result["success"]:
            st.session_state.account_info = info_result["data"]
            st.session_state.connected = True
            return True, "Connected successfully!"
        else:
            st.session_state.connected = True
            return True, "Connected (info endpoint not available)"
    return False, result.get("error", "Connection failed")


def render_sidebar():
    """Render the sidebar with connection settings."""
    st.sidebar.title("🔧 Connection Settings")

    # API URL input
    api_url = st.sidebar.text_input(
        "API URL",
        value=st.session_state.api_url,
        placeholder="https://your-app.railway.app",
        help="The Railway URL of your Google Ads MCP wrapper"
    )

    # API Token input
    api_token = st.sidebar.text_input(
        "API Token",
        value=st.session_state.api_token,
        type="password",
        help="Your API authentication token"
    )

    # Update session state
    st.session_state.api_url = api_url
    st.session_state.api_token = api_token

    # Connect button
    if st.sidebar.button("🔌 Connect", use_container_width=True):
        if not api_url or not api_token:
            st.sidebar.error("Please enter both URL and token")
        else:
            with st.spinner("Connecting..."):
                success, message = test_connection()
                if success:
                    st.sidebar.success(message)
                else:
                    st.sidebar.error(message)

    # Show connection status
    if st.session_state.connected:
        st.sidebar.success("✅ Connected")
        if st.session_state.account_info:
            st.sidebar.markdown("---")
            st.sidebar.markdown("**Account Info:**")
            info = st.session_state.account_info
            st.sidebar.text(f"Client: {info.get('client', 'N/A')}")
            st.sidebar.text(f"Customer ID: {info.get('customer_id', 'N/A')}")
            st.sidebar.text(f"MCC ID: {info.get('mcc_id', 'N/A')}")
    else:
        st.sidebar.warning("⚠️ Not connected")


def render_search_form():
    """Render the search form."""
    st.subheader("🔍 Search Google Ads Data")

    col1, col2 = st.columns([1, 2])

    with col1:
        # Resource selection
        resource_options = list(RESOURCE_FIELDS.keys())
        selected_resource = st.selectbox(
            "Resource",
            options=resource_options,
            help="Select the Google Ads resource to query"
        )

        # Get actual resource name (remove description suffix)
        actual_resource = selected_resource.split(" (")[0]

        # Limit
        limit = st.number_input(
            "Limit",
            min_value=1,
            max_value=10000,
            value=100,
            help="Maximum number of rows to return"
        )

    with col2:
        # Fields selection
        default_fields = RESOURCE_FIELDS.get(selected_resource, [])
        fields_input = st.text_area(
            "Fields (one per line)",
            value="\n".join(default_fields),
            height=200,
            help="Enter the fields to fetch, one per line"
        )
        fields = [f.strip() for f in fields_input.strip().split("\n") if f.strip()]

    # Conditions
    st.markdown("**Conditions (optional)**")
    conditions_input = st.text_area(
        "WHERE conditions (one per line)",
        placeholder="campaign.status = 'ENABLED'\nmetrics.impressions > 0",
        height=100,
        help="Add filter conditions, one per line. They will be combined with AND."
    )
    conditions = [c.strip() for c in conditions_input.strip().split("\n") if c.strip()]

    # Order by
    col3, col4 = st.columns(2)
    with col3:
        order_by = st.text_input(
            "Order by (optional)",
            placeholder="metrics.impressions DESC",
            help="Field to sort results by"
        )

    # Search button
    if st.button("🚀 Search", type="primary", use_container_width=True):
        if not st.session_state.connected:
            st.error("Please connect to the API first")
            return

        if not fields:
            st.error("Please select at least one field")
            return

        # Build request payload
        payload = {
            "resource": actual_resource,
            "fields": fields,
            "limit": limit,
        }

        if conditions:
            payload["conditions"] = conditions

        if order_by:
            payload["orderings"] = [order_by]

        # Show the query being made
        with st.expander("📝 Request Payload"):
            st.json(payload)

        # Make the request
        with st.spinner("Searching..."):
            result = make_request("/api/search", method="POST", data=payload)

        if result["success"]:
            st.session_state.last_result = result["data"]
            st.success(f"Query successful!")
        else:
            st.error(f"Error: {result.get('error', 'Unknown error')}")


def render_results():
    """Render the search results."""
    if st.session_state.last_result is None:
        return

    st.subheader("📊 Results")

    data = st.session_state.last_result.get("result", [])

    if not data:
        st.info("No results found")
        return

    # Handle different result formats
    if isinstance(data, list):
        if len(data) > 0:
            # Flatten nested dictionaries for display
            flat_data = []
            for row in data:
                flat_row = {}
                for key, value in row.items():
                    if isinstance(value, dict):
                        for sub_key, sub_value in value.items():
                            flat_row[f"{key}.{sub_key}"] = sub_value
                    else:
                        flat_row[key] = value
                flat_data.append(flat_row)

            df = pd.DataFrame(flat_data)
            st.dataframe(df, use_container_width=True)

            # Download button
            csv = df.to_csv(index=False)
            st.download_button(
                "📥 Download CSV",
                csv,
                "google_ads_data.csv",
                "text/csv",
                use_container_width=True
            )

            st.caption(f"Showing {len(data)} rows")
    else:
        st.json(data)

    # Raw JSON expander
    with st.expander("🔧 Raw JSON Response"):
        st.json(st.session_state.last_result)


def main():
    """Main application entry point."""
    init_session_state()

    # Header
    st.title("📊 VentureLab Google Ads")
    st.markdown("Query your Google Ads data through the MCP connector")
    st.markdown("---")

    # Sidebar
    render_sidebar()

    # Main content
    if not st.session_state.connected:
        st.info("👈 Enter your API URL and token in the sidebar to get started")

        # Quick start guide
        with st.expander("📖 Quick Start Guide"):
            st.markdown("""
            ### How to use this app

            1. **Get your API URL**: This is your Railway deployment URL (e.g., `https://your-app.railway.app`)

            2. **Get your API Token**: The token configured in your Railway environment variables

            3. **Connect**: Click the Connect button to test the connection

            4. **Search**: Once connected, use the search form to query Google Ads data

            ### Available Resources

            - `campaign` - Campaign data
            - `ad_group` - Ad group data
            - `ad_group_ad` - Individual ads
            - `keyword_view` - Keyword performance
            - `campaign_budget` - Budget information
            - `customer` - Account information
            - And more...

            ### Example Query

            To get all enabled campaigns with their metrics:
            - Resource: `campaign`
            - Fields: `campaign.id`, `campaign.name`, `campaign.status`
            - Conditions: `campaign.status = 'ENABLED'`
            """)
    else:
        render_search_form()
        st.markdown("---")
        render_results()


if __name__ == "__main__":
    main()
