from __future__ import annotations

from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsBrandOwner
from ai.models import Character
from ai.serializers import CharacterSerializer, VideoProjectSerializer
from ai.services.characters import (
    CharacterError,
    archive_character,
    character_from_presenter,
    create_character,
    delete_character,
    duplicate_character,
    get_owned_character,
    restore_character,
    update_character,
    visible_characters,
    voice_catalog,
)
from ai.services.master_character import MasterCharacterService
from ai.views import _error_response, _owned_project


def _character_or_404(request, pk, *, include_archived: bool = True) -> Character:
    try:
        return get_owned_character(request.user, pk, include_archived=include_archived)
    except Character.DoesNotExist as exc:
        raise Http404() from exc


class VoiceCatalogView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        return Response(voice_catalog())


class CharacterListView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        include_archived = str(request.query_params.get("archived") or "").lower() in {"1", "true", "yes"}
        characters = visible_characters(request.user, request, include_archived=include_archived)
        return Response(CharacterSerializer(characters, many=True).data)

    def post(self, request):
        try:
            character = create_character(request.user, request.data, request)
        except CharacterError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return _error_response(exc)
        return Response(CharacterSerializer(character).data, status=status.HTTP_201_CREATED)


class CharacterDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        return Response(CharacterSerializer(_character_or_404(request, pk)).data)

    def patch(self, request, pk):
        character = _character_or_404(request, pk)
        try:
            update_character(character, request.data, request)
        except CharacterError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return _error_response(exc)
        character.refresh_from_db()
        return Response(CharacterSerializer(character).data)

    def delete(self, request, pk):
        character = _character_or_404(request, pk)
        try:
            delete_character(character)
        except CharacterError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CharacterMasterReferenceView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        character = _character_or_404(request, pk, include_archived=False)
        try:
            MasterCharacterService().generate(character)
        except CharacterError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return _error_response(exc)
        character = get_owned_character(request.user, pk, include_archived=False)
        return Response(CharacterSerializer(character).data)


class CharacterMasterApproveView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        character = _character_or_404(request, pk, include_archived=False)
        version = request.data.get("version")
        try:
            version_number = int(version) if version not in (None, "") else None
            MasterCharacterService().approve(character, version_number)
        except (TypeError, ValueError):
            return Response({"detail": "Choose a master version to approve."}, status=status.HTTP_400_BAD_REQUEST)
        except CharacterError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return _error_response(exc)
        character = get_owned_character(request.user, pk, include_archived=False)
        return Response(CharacterSerializer(character).data)


class CharacterArchiveView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        character = archive_character(_character_or_404(request, pk))
        return Response(CharacterSerializer(character).data)


class CharacterRestoreView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        character = restore_character(_character_or_404(request, pk))
        return Response(CharacterSerializer(character).data)


class CharacterDuplicateView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        character = _character_or_404(request, pk)
        try:
            clone = duplicate_character(character, str(request.data.get("name") or ""))
        except Exception as exc:
            return _error_response(exc)
        return Response(CharacterSerializer(clone).data, status=status.HTTP_201_CREATED)


class CharacterVideosView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request, pk):
        character = _character_or_404(request, pk)
        projects = [
            row.project
            for row in character.video_configs.select_related("project", "project__product").order_by("-project__created_at")
        ]
        return Response(VideoProjectSerializer(projects, many=True).data)


class CharacterFromPresenterView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request):
        try:
            project = _owned_project(request, request.data.get("project_id"))
            character = character_from_presenter(project, request.data)
        except CharacterError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return _error_response(exc)
        return Response(CharacterSerializer(character).data, status=status.HTTP_201_CREATED)
