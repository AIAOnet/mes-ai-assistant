"""Dynamic MES relationship graph built from governed controller and RAG data."""
from __future__ import annotations
import math
import os
import re
import json
import hashlib
import threading
from collections import deque
from pathlib import Path

class OntologyValidationError(ValueError):
    pass

class MESOntology:
    SENSOR_DEFINITIONS = (
        ("PRESSURE-SENSOR-01", "Pressure sensor", "pressure", "bar"),
        ("TEMPERATURE-SENSOR-01", "Temperature sensor", "temperature", "°C"),
        ("RPM-SENSOR-01", "Motor speed sensor", "rpm", "RPM"),
    )
    ENTITY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")
    RELATION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")

    def __init__(self, controller, knowledge_store, manual_path=None):
        self.controller, self.knowledge_store = controller, knowledge_store
        self.embedder = knowledge_store.embedder
        self.search_mode = os.getenv("MES_ONTOLOGY_SEARCH_MODE", "hybrid").strip().lower()
        try: self.semantic_weight = max(0.0, min(1.0, float(os.getenv("MES_ONTOLOGY_SEMANTIC_WEIGHT", "0.60"))))
        except ValueError: self.semantic_weight = 0.60
        self._vector_cache = {}
        self.last_embedding_error = ""
        configured_path = os.getenv("MES_ONTOLOGY_MANUAL_TRIPLES_PATH", "").strip()
        self.manual_path = Path(manual_path or configured_path or (knowledge_store.root / "ontology" / "manual_triples.json"))
        self._manual_lock = threading.RLock()
        self._manual_triples = self._load_manual_triples()

    def _load_manual_triples(self):
        if not self.manual_path.exists():
            return []
        try:
            payload = json.loads(self.manual_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_manual_triples(self):
        self.manual_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.manual_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._manual_triples, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.manual_path)

    @classmethod
    def _validate_entity_id(cls, value, field):
        identifier = str(value).strip()
        if not cls.ENTITY_PATTERN.fullmatch(identifier):
            raise OntologyValidationError(f"{field} must be 1-100 characters using letters, numbers, '.', ':', '_' or '-'")
        return identifier

    @classmethod
    def _normalize_relation(cls, value):
        relation = re.sub(r"[\s-]+", "_", str(value).strip()).upper()
        if not cls.RELATION_PATTERN.fullmatch(relation):
            raise OntologyValidationError("Predicate must be 1-80 characters using letters, numbers or underscores")
        return relation

    def list_manual(self):
        with self._manual_lock:
            return [dict(triple) for triple in self._manual_triples]

    def add_manual(self, subject, predicate, object_):
        subject = self._validate_entity_id(subject, "Subject")
        object_ = self._validate_entity_id(object_, "Object")
        predicate = self._normalize_relation(predicate)
        if subject == object_:
            raise OntologyValidationError("Subject and object must be different")
        digest = hashlib.sha256(f"{subject}\0{predicate}\0{object_}".encode()).hexdigest()[:20]
        triple = {"id": digest, "subject": subject, "predicate": predicate, "object": object_}
        with self._manual_lock:
            if any(item["id"] == digest for item in self._manual_triples):
                raise OntologyValidationError("This triple already exists")
            self._manual_triples.append(triple)
            self._save_manual_triples()
        self._vector_cache.clear()
        return dict(triple)

    def delete_manual(self, triple_id):
        with self._manual_lock:
            original = len(self._manual_triples)
            self._manual_triples = [item for item in self._manual_triples if item.get("id") != triple_id]
            if len(self._manual_triples) == original:
                return False
            self._save_manual_triples()
        self._vector_cache.clear()
        return True

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
        existing_edges={(edge["source"],edge["relation"],edge["target"]) for edge in edges}
        for triple in self.list_manual():
            for identifier in (triple["subject"], triple["object"]):
                if identifier not in nodes:
                    nodes[identifier]=self._node(identifier,"ManualEntity",identifier.replace("_"," "))
            edge_key=(triple["subject"],triple["predicate"],triple["object"])
            if edge_key not in existing_edges:
                edges.append(self._edge(*edge_key)); existing_edges.add(edge_key)
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
        candidates=[]
        for node in nodes.values():
            haystack=self._terms(f"{node['id']} {node['type']} {node['label']} {' '.join(map(str,node['properties'].values()))}")
            score=len(expanded & haystack)
            if node["id"].lower() in query.lower(): score+=4
            candidates.append({"id":node["id"],"lexical":float(score),"semantic":0.0})
        hybrid=self.search_mode=="hybrid" and self.embedder.configured
        if hybrid:
            try:
                texts={identifier:self._embedding_text(node) for identifier,node in nodes.items()}
                missing=[(identifier,text) for identifier,text in texts.items() if identifier not in self._vector_cache or self._vector_cache[identifier][0]!=text]
                if missing:
                    vectors=self.embedder.embed([text for _,text in missing])
                    for (identifier,text),vector in zip(missing,vectors): self._vector_cache[identifier]=(text,vector)
                query_vector=self.embedder.embed([query])[0]
                for item in candidates: item["semantic"]=max(0.0,self._cosine(query_vector,self._vector_cache[item["id"]][1]))
                self.last_embedding_error=""
            except Exception as error:
                hybrid=False; self.last_embedding_error=str(error)
        maximum=max((x["lexical"] for x in candidates),default=1) or 1
        for item in candidates:
            lexical=item["lexical"]/maximum
            item["score"]=(1-self.semantic_weight)*lexical+self.semantic_weight*item["semantic"] if hybrid else lexical
        ranked=[x for x in sorted(candidates,key=lambda item:item["score"],reverse=True) if x["score"]>0]
        seeds=[item["id"] for item in ranked[:8]]
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
        seed_scores=[{"id":item["id"],"score":round(item["score"],4),"lexical_score":round(item["lexical"]/maximum,4),"semantic_score":round(item["semantic"],4)} for item in ranked[:8]]
        return {"query":query,"search_mode":"hybrid" if hybrid else "lexical","seed_ids":seeds,"seed_scores":seed_scores,"nodes":[nodes[x] for x in selected],"edges":selected_edges,"count":len(selected),"depth":depth}

    @staticmethod
    def _embedding_text(node):
        stable={key:value for key,value in node["properties"].items() if key not in {"current_value","status","triggered_time"}}
        return f"MES {node['type']}: {node['label']}. Identifier {node['id']}. " + " ".join(f"{key} {value}" for key,value in stable.items() if value not in {None,""})

    @staticmethod
    def _cosine(first,second):
        if not first or not second or len(first)!=len(second): return 0.0
        denominator=math.sqrt(sum(x*x for x in first))*math.sqrt(sum(x*x for x in second))
        return sum(x*y for x,y in zip(first,second))/denominator if denominator else 0.0

    def entity(self, identifier, role="viewer"):
        graph=self.build(role); node=next((x for x in graph["nodes"] if x["id"]==identifier),None)
        if node is None:return None
        edges=[x for x in graph["edges"] if identifier in {x["source"],x["target"]}]
        related_ids={x["target"] if x["source"]==identifier else x["source"] for x in edges}
        return {"entity":node,"relationships":edges,"related":[x for x in graph["nodes"] if x["id"] in related_ids]}

    def status(self, role="viewer"):
        graph=self.build(role); counts={}
        for node in graph["nodes"]:counts[node["type"]]=counts.get(node["type"],0)+1
        hybrid=self.search_mode=="hybrid" and self.embedder.configured
        return {"phase":8,"nodes":len(graph["nodes"]),"relationships":len(graph["edges"]),"manual_triples":len(self.list_manual()),"entity_types":counts,"search_mode":"hybrid" if hybrid else "lexical","semantic_weight":self.semantic_weight,"lexical_weight":1-self.semantic_weight,"embedding_model":self.embedder.model or None,"cached_entity_vectors":len(self._vector_cache),"last_embedding_error":self.last_embedding_error or None}
