from __future__ import annotations

import json

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsBrandOwner
from ai.models import BulkGeneration
from ai.serializers import BulkGenerationSerializer
from ai.services.bulk_studio import BulkVideoGenerationService
from ai.views import _error_response, _owned_product


def _owned_bulk(request, pk) -> BulkGeneration:
    return get_object_or_404(
        BulkGeneration.objects.select_related("product", "character").prefetch_related(
            "items__video_project"
        ),
        pk=pk,
        owner=request.user,
    )


class BulkVideoListCreateView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        rows = (
            BulkGeneration.objects.filter(owner=request.user)
            .select_related("product", "character")
            .prefetch_related("items__video_project")
        )
        return Response(BulkGenerationSerializer(rows, many=True).data)

    def post(self, request):
        product_id = request.data.get("product_id") or request.data.get("product")
        if not product_id:
            return Response({"detail": "Select a product."}, status=status.HTTP_400_BAD_REQUEST)
        product = _owned_product(request, product_id)
        try:
            payload = {key: request.data.get(key) for key in request.data}
            payload["product"] = product
            if hasattr(request.data, "getlist"):
                ids = request.data.getlist("character_ids")
                if ids:
                    payload["character_ids"] = ids
            for key in ("locks", "variables", "character_ids"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip().startswith(("{", "[")):
                    try:
                        payload[key] = json.loads(value)
                    except json.JSONDecodeError:
                        pass
            bulk = BulkVideoGenerationService().create(
                request.user,
                payload,
                files=request.FILES,
            )
        except Exception as exc:
            return _error_response(exc)
        return Response(BulkGenerationSerializer(_owned_bulk(request, bulk.pk)).data, status=status.HTTP_201_CREATED)


class BulkVideoDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        bulk = BulkVideoGenerationService().refresh(_owned_bulk(request, pk))
        return Response(BulkGenerationSerializer(_owned_bulk(request, bulk.pk)).data)


class BulkVideoAnalyzeView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        try:
            bulk = BulkVideoGenerationService().analyze_reference(_owned_bulk(request, pk), request.data)
        except Exception as exc:
            return _error_response(exc)
        return Response(BulkGenerationSerializer(_owned_bulk(request, bulk.pk)).data)


class BulkVideoPlanView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        try:
            bulk = BulkVideoGenerationService().generate_plan(_owned_bulk(request, pk), payload=request.data)
        except Exception as exc:
            return _error_response(exc)
        return Response(BulkGenerationSerializer(_owned_bulk(request, bulk.pk)).data)


class BulkVideoPlanEditView(APIView):
    permission_classes = [IsBrandOwner]

    def patch(self, request, pk):
        try:
            bulk = BulkVideoGenerationService().update_plan(_owned_bulk(request, pk), request.data)
        except Exception as exc:
            return _error_response(exc)
        return Response(BulkGenerationSerializer(_owned_bulk(request, bulk.pk)).data)


class BulkVideoGenerateView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        try:
            bulk = BulkVideoGenerationService().start_generation(_owned_bulk(request, pk), request.data)
        except Exception as exc:
            return _error_response(exc)
        return Response(
            BulkGenerationSerializer(_owned_bulk(request, bulk.pk)).data,
            status=status.HTTP_202_ACCEPTED,
        )


class BulkVideoRetryView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        try:
            bulk = BulkVideoGenerationService().retry_failed(_owned_bulk(request, pk))
        except Exception as exc:
            return _error_response(exc)
        return Response(
            BulkGenerationSerializer(_owned_bulk(request, bulk.pk)).data,
            status=status.HTTP_202_ACCEPTED,
        )


class BulkVideoCancelView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        try:
            bulk = BulkVideoGenerationService().cancel(_owned_bulk(request, pk))
        except Exception as exc:
            return _error_response(exc)
        return Response(BulkGenerationSerializer(_owned_bulk(request, bulk.pk)).data)


class BulkVideoStatusView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        bulk = BulkVideoGenerationService().refresh(_owned_bulk(request, pk))
        return Response(BulkGenerationSerializer(_owned_bulk(request, bulk.pk)).data)
