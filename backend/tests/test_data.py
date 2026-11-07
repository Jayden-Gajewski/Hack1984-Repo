from app.data import load_json


def test_reference_data_shapes():
    for broker in load_json("brokers.json"):
        assert set(broker) == {"id", "name", "domain", "opt_out_url"}
    for company in load_json("companies.json"):
        assert set(company) == {"id", "name", "domains", "privacy_url"}
    for source in load_json("breach_sources.json"):
        assert set(source) == {"state", "name", "domain"}


def test_mock_inbox_has_a_proven_match_and_a_legit_email():
    """The demo needs one alias hit (step 5) and one legitimate email that isn't flagged."""
    aliases = {a["alias"]: a for a in load_json("mock_aliases.json")["aliases"]}
    outside = legit = 0
    for message in load_json("mock_inbox.json")["messages"]:
        domains = aliases[message["to"]]["company_domains"]
        sender = message["from"].split("@")[1]
        if any(sender == d or sender.endswith("." + d) for d in domains):
            legit += 1
        else:
            outside += 1
    assert outside >= 1 and legit >= 1


def test_fixtures_stay_fictional():
    for alias in load_json("mock_aliases.json")["aliases"]:
        assert all(d.endswith(".example") for d in alias["company_domains"])
    for message in load_json("mock_inbox.json")["messages"]:
        assert message["from"].endswith(".example")
