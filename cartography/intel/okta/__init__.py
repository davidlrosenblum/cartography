import logging

from cartography.util import run_cleanup_job
from cartography.intel.okta import applications
from cartography.intel.okta import factors
from cartography.intel.okta import groups
from cartography.intel.okta import organization
from cartography.intel.okta import origins
from cartography.intel.okta import roles
from cartography.intel.okta import users

from okta.framework.ApiClient import ApiClient
from okta.framework.OktaError import OktaError

logger = logging.getLogger(__name__)

OKTA_API_KEY = os.environ.get('CREDENTIALS_OKTA_API_KEY')

OKTA_ORG_ID = os.environ.get("OKTA_ORG_ID")


def is_last_page(response):
    """
    Determine if we are at the last page of a Paged result flow
    :param response: server response
    :return: boolean indicating if we are at the last page or not
    """
    # from https://github.com/okta/okta-sdk-python/blob/master/okta/framework/PagedResults.py
    return not ("next" in response.links)


def get_user_id_from_graph(neo4j_session, okta_org_id):
    """
    Get user id for the okta organization rom the graph
    :param neo4j_session: session with the Neo4j server
    :param okta_org_id: okta organization id
    :return: Array od user id
    """
    group_query = "MATCH (:OktaOrganization{id: {ORG_ID}})-[:RESOURCE]->(user:OktaUser) return user.id as id"

    result = neo4j_session.run(group_query, ORG_ID=okta_org_id)

    users = [r['id'] for r in result]

    return users


def get_okta_groups_id_from_graph(neo4j_session, okta_org_id):
    """
    Get the okta groups from the graph
    :param neo4j_session: session with the Neo4j server
    :param okta_org_id: okta organization id
    :return: Array of group id
    """
    group_query = "MATCH (:OktaOrganization{id: {ORG_ID}})-[:RESOURCE]->(group:OktaGroup) return group.id as id"

    result = neo4j_session.run(group_query, ORG_ID=okta_org_id)

    groups = [r['id'] for r in result]

    return groups


def create_api_client(okta_org, path_name, api_key):
    """
    Create Okta ApiClient
    :param okta_org: Okta organization name
    :param path_name: API Path
    :param api_key: Okta api key
    :return: Instance of ApiClient
    """
    api_client = ApiClient(
        base_url=f"https://{okta_org}.okta.com/",
        pathname=path_name,
        api_token=api_key,
    )

    return api_client


def get_okta_api_key():
    """
    Get Okta api key
    :return: api key
    """
    return OKTA_API_KEY


def start_okta_ingestion(session, config):
    """
    Starts the OKTA ingestion process
    :param session: The Neo4j session
    :param config: A `cartography.config` object
    :return: Nothing
    """
    sync(session, config)


def sync(neo4j_session, config):
    """
    Starts the Okta ingestion process by initializing Okta API session and pulling necessary information
    :param neo4j_session: The Neo4j session
    :param config: A `cartography.config` object
    :return: Nothing
    """

    logger.debug(f"Starting Okta sync on {OKTA_ORG_ID}")

    common_job_parameters = {
        "UPDATE_TAG": config.update_tag,
        "OKTA_ORG_ID": OKTA_ORG_ID,
    }

    organization.create_okta_organization(neo4j_session, OKTA_ORG_ID, config.update_tag)
    users.sync_okta_users(neo4j_session, OKTA_ORG_ID, config.update_tag)
    groups.sync_okta_groups(neo4j_session, OKTA_ORG_ID, config.update_tag)
    applications.sync_okta_applications(neo4j_session, OKTA_ORG_ID, config.update_tag)
    factors.sync_users_factors(neo4j_session, OKTA_ORG_ID, config.update_tag)
    origins.sync_trusted_origins(neo4j_session, OKTA_ORG_ID, config.update_tag)

    # need creds with permission
    # soft fail as some won't be able to get such high priv token
    # when we get the E0000006 error
    # see https://developer.okta.com/docs/reference/error-codes/
    try:
        roles.sync_roles(neo4j_session, OKTA_ORG_ID, config.update_tag)
    except OktaError as okta_error:
        logger.warning(f"Unable to pull admin roles got {okta_error}")

        # Getting roles requires super admin which most won't be able to get easily
        if okta_error.error_code == "E0000006":
            print("Unable to sync admin roles - api token needs admin rights to pull admin roles data")

    _cleanup_okta_organizations(neo4j_session, common_job_parameters)


def _cleanup_okta_organizations(session, common_job_parameters):
    """
    Remove stale Okta organization
    :param session: The Neo4j session
    :param common_job_parameters: Parameters to carry to the cleanup job
    :return: Nothing
    """

    run_cleanup_job('okta_import_cleanup.json', session, common_job_parameters)