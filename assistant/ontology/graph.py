"""Dynamic MES relationship graph built from governed controller and RAG data."""
from __future__ import annotations
import re
from collections import deque

class MESOntology:
    SENSOR_DEFINITIONS = (
        ("PRESSURE-SENSOR-01", "Pressure sensor", "pressure", "bar"),
        ("TEMPERATURE-SENSOR-01", "Temperature sensor", "temperature", "°C"),
        ("RPM-SENSOR-01", "Motor speed sensor", "rpm", "RPM"),
    )
    def __init__(self, controller, knowledge_store):
        self.controller, self.knowledge_store = controller, knowledge_store

    @staticmethod
    def _node(identifier, kind, label, **properties):
        return {"id":str(identifier),"type":kind,"label":str(label),"properties":properties}
    @staticmethod
    def _edge(source, relation, target):
        return {"source":str(source),"relation":relation,"target":str(target)}

    def build(self, role="viewer"):
        state=self.controller.snapshot(); machine=state.get("machine_id","MACHINE-01")
        nodes={machine:self._node(machine,"Machine",machine,status=state.get("machine_status"))}; edges=[]
        for sensor_id,label,metric,unit in self.SENSOR_DEFINITIONS:
            nodes[sensor_id]=self._node(sensor_id,"Sensor",label,metric=metric,unit=unit,current_value=state.get(metric))
            edges.append(self._edge(machine,"HAS_SENSOR",sensor_id))
        alarm_types={}
        for alarm in state.get("alarms",[]):
            alarm_id=str(alarm["id"]); alarm_type=str(alarm["type"]).upper(); type_id=f"ALARM-TYPE:{alarm_type}"
            nodes[type_id]=self._node(type_id,"AlarmType",alarm_type.replace("_"," "),alarm_type=alarm_type); alarm_types[alarm_type]=type_id
            nodes[alarm_id]=self._node(alarm_id,"Alarm",alarm_type,status=alarm.get("status"),severity=alarm.get("severity"),triggered_time=alarm.get("triggered_time"))
            edges += [self._edge(machine,"HAS_ALARM",alarm_id),self._edge(alarm_id,"INSTANCE_OF",type_id)]
            if "PRESSURE" in alarm_type: edges.append(self._edge("PRESSURE-SENSOR-01","CAN_TRIGGER",type_id))
            if "TEMPERATURE" in alarm_type: edges.append(self._edge("TEMPERATURE-SENSOR-01","CAN_TRIGGER",type_id))
        for task in state.get("tasks",[]):
            task_id=f"TASK:{task['id']}"; nodes[task_id]=self._node(task_id,"MaintenanceTask",task.get("description") or task_id,status=task.get("status"),priority=task.get("priority"))
            edges.append(self._edge(machine,"HAS_MAINTENANCE_TASK",task_id))
            if task.get("alarm_id") in nodes: edges.append(self._edge(task_id,"RESPONDS_TO",task["alarm_id"]))
        for order in state.get("production_orders",[]):
            order_id=f"ORDER:{order['id']}"; nodes[order_id]=self._node(order_id,"ProductionOrder",order.get("product_name") or order["id"],order_id=order["id"],status=order.get("status"),target_quantity=order.get("target_quantity"))
            edges.append(self._edge(machine,"EXECUTES",order_id))
        for document in self.knowledge_store.list(role):
            doc_id=f"DOCUMENT:{document['id']}"; nodes[doc_id]=self._node(doc_id,"Procedure",document["title"],document_id=document["id"],version=document.get("version"),filename=document["filename"])
            if document.get("machine_id") in nodes: edges.append(self._edge(document["machine_id"],"HAS_PROCEDURE",doc_id))
            alarm_type=str(document.get("alarm_type") or "").upper()
            if alarm_type:
                type_id=f"ALARM-TYPE:{alarm_type}"
                if type_id not in nodes: nodes[type_id]=self._node(type_id,"AlarmType",alarm_type.replace("_"," "),alarm_type=alarm_type)
                edges.append(self._edge(type_id,"REQUIRES_PROCEDURE",doc_id))
        return {"nodes":list(nodes.values()),"edges":edges}

    @staticmethod
    def _terms(text):
        stop={"the","a","an","to","on","of","for","and","or","everything","related","show","what","all"}
        return {term for term in re.findall(r"[a-z0-9]+",text.lower())
                if term not in stop and not term.isdigit()}
    def search(self, query, role="viewer", depth=2, limit=60):
        graph=self.build(role); nodes={x["id"]:x for x in graph["nodes"]}; terms=self._terms(query)
        aliases={"hydraulic":{"pressure"},"heat":{"temperature"},"fault":{"alarm"},"job":{"order"},"work":{"maintenance"}}
        expanded=set(terms)
        for term in terms: expanded.update(aliases.get(term,set()))
        seeds=[]
        for node in nodes.values():
            haystack=self._terms(f"{node['id']} {node['type']} {node['label']} {' '.join(map(str,node['properties'].values()))}")
            score=len(expanded & haystack)
            if node["id"].lower() in query.lower(): score+=4
            if score: seeds.append((score,node["id"]))
        seeds=[identifier for _,identifier in sorted(seeds,reverse=True)[:8]]
        adjacency={identifier:[] for identifier in nodes}
        for edge in graph["edges"]:
            adjacency.setdefault(edge["source"],[]).append((edge,edge["target"])); adjacency.setdefault(edge["target"],[]).append((edge,edge["source"]))
        selected=set(seeds); queue=deque((seed,0) for seed in seeds)
        while queue and len(selected)<limit:
            current,level=queue.popleft()
            if level>=max(1,min(int(depth),4)): continue
            for _,neighbor in adjacency.get(current,[]):
                if neighbor not in selected: selected.add(neighbor); queue.append((neighbor,level+1))
        selected_edges=[x for x in graph["edges"] if x["source"] in selected and x["target"] in selected]
        return {"query":query,"seed_ids":seeds,"nodes":[nodes[x] for x in selected],"edges":selected_edges,"count":len(selected),"depth":depth}

    def entity(self, identifier, role="viewer"):
        graph=self.build(role); node=next((x for x in graph["nodes"] if x["id"]==identifier),None)
        if node is None:return None
        edges=[x for x in graph["edges"] if identifier in {x["source"],x["target"]}]
        related_ids={x["target"] if x["source"]==identifier else x["source"] for x in edges}
        return {"entity":node,"relationships":edges,"related":[x for x in graph["nodes"] if x["id"] in related_ids]}

    def status(self, role="viewer"):
        graph=self.build(role); counts={}
        for node in graph["nodes"]:counts[node["type"]]=counts.get(node["type"],0)+1
        return {"phase":8,"nodes":len(graph["nodes"]),"relationships":len(graph["edges"]),"entity_types":counts}
