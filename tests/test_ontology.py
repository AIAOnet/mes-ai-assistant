import tempfile
import unittest

from assistant.knowledge import KnowledgeStore
from assistant.ontology import MESOntology
from assistant.orchestrator import AssistantMode, AssistantOrchestrator, Intent
from assistant.tools import MESReadTools

class FakeController:
    def snapshot(self):
        return {"machine_id":"MACHINE-01","machine_status":"STOPPED","pressure":105,
                "temperature":58,"rpm":0,"alarms":[{"id":"A-100","type":"HIGH_PRESSURE",
                "status":"ACTIVE","severity":"HIGH","triggered_time":"2026-08-29T10:32:00Z"}],
                "tasks":[{"id":44,"alarm_id":"A-100","description":"Inspect hydraulics",
                "status":"OPEN","priority":"HIGH"}],"production_orders":[{"id":"PO-1001",
                "product_name":"Drill component","status":"RUNNING","target_quantity":100}]}

class OntologyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.knowledge=KnowledgeStore(self.temp.name)
        self.document=self.knowledge.add("procedure.md",b"Inspect the hydraulic circuit before safe restart",
                                         title="Hydraulic SOP",machine_id="MACHINE-01",
                                         alarm_type="HIGH_PRESSURE",roles=["admin","operator"])
        self.ontology=MESOntology(FakeController(),self.knowledge)
    def tearDown(self): self.temp.cleanup()

    def test_graph_connects_mes_entities_and_procedure(self):
        graph=self.ontology.build("operator"); relations={x["relation"] for x in graph["edges"]}
        self.assertTrue({"HAS_SENSOR","HAS_ALARM","INSTANCE_OF","REQUIRES_PROCEDURE",
                         "RESPONDS_TO","EXECUTES"}.issubset(relations))
        self.assertIn(f"DOCUMENT:{self.document['id']}",{x["id"] for x in graph["nodes"]})

    def test_graph_hides_procedure_from_unauthorized_role(self):
        graph=self.ontology.build("viewer")
        self.assertNotIn(f"DOCUMENT:{self.document['id']}",{x["id"] for x in graph["nodes"]})

    def test_traversal_returns_related_pressure_entities(self):
        result=self.ontology.search("everything related to pressure on Machine 01","operator",2)
        identifiers={x["id"] for x in result["nodes"]}
        self.assertIn("MACHINE-01",identifiers); self.assertIn("PRESSURE-SENSOR-01",identifiers)
        self.assertIn("ALARM-TYPE:HIGH_PRESSURE",identifiers)

    def test_orchestrator_routes_relationship_questions(self):
        tools=MESReadTools(FakeController(),self.knowledge,self.ontology)
        orchestrator=AssistantOrchestrator(tools)
        plan=orchestrator.plan("Show everything related to the pressure problem on Machine 01")
        self.assertEqual((plan.mode,plan.intent,plan.tool),
                         (AssistantMode.DATA,Intent.ONTOLOGY_SEARCH,"search_ontology"))
        result=orchestrator.execute(plan,role="operator")
        self.assertEqual(result.tool,"search_ontology")
