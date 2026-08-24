from __future__ import annotations
from urllib.parse import quote
from .base import CollectorResult
from .common import get

SERVER_ROOT = 'https://maps.canyonco.org/arcgisserver/rest/services'
DSD_ROOT = SERVER_ROOT + '/DSD'


def _json(url: str):
    response = get(url)
    payload = response.json()
    if isinstance(payload, dict) and payload.get('error'):
        raise RuntimeError(f"ArcGIS error: {payload['error']}")
    return payload


def candidate_layers(folder_payload: dict, service_payloads: dict[str, dict]):
    out = []
    for service in folder_payload.get('services') or []:
        name = str(service.get('name') or '').strip()
        service_type = str(service.get('type') or '').strip()
        if not name or service_type not in {'MapServer', 'FeatureServer'}:
            continue
        meta = service_payloads.get(name) or {}
        for layer in meta.get('layers') or []:
            layer_name = str(layer.get('name') or '').strip()
            hay = f'{name} {layer_name}'.lower()
            if 'permit' not in hay and 'building' not in hay and 'development' not in hay:
                continue
            out.append({
                'service': name,
                'service_type': service_type,
                'layer_id': layer.get('id'),
                'layer_name': layer_name,
            })
    return out


class CanyonCountyDiscoveryCollector:
    name = 'Canyon County'
    landing_url = DSD_ROOT

    def collect(self):
        folder = _json(DSD_ROOT + '?f=json')
        services = [
            s for s in (folder.get('services') or [])
            if s.get('name') and s.get('type') in {'MapServer', 'FeatureServer'}
        ][:30]
        payloads = {}
        for service in services:
            name = str(service['name'])
            service_type = str(service['type'])
            url = f"{SERVER_ROOT}/{quote(name, safe='/')}/{service_type}?f=json"
            try:
                payloads[name] = _json(url)
            except Exception as exc:
                payloads[name] = {'_error': f'{type(exc).__name__}: {exc}'}
        candidates = candidate_layers(folder, payloads)
        details = []
        for candidate in candidates[:12]:
            name = candidate['service']
            service_type = candidate['service_type']
            layer_id = candidate['layer_id']
            layer_url = f"{SERVER_ROOT}/{quote(name, safe='/')}/{service_type}/{layer_id}?f=json"
            try:
                layer = _json(layer_url)
                fields = [str(f.get('name') or '') for f in (layer.get('fields') or [])][:30]
                details.append({**candidate, 'fields': fields})
            except Exception as exc:
                details.append({**candidate, 'error': f'{type(exc).__name__}: {exc}'})
        service_names = [f"{s.get('name')}:{s.get('type')}" for s in services]
        raise RuntimeError(
            f'GIS discovery only; services={service_names[:20]}; candidate_layers={details}'
        )
