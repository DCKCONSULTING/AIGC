import logging

from accounts.models import User
from accounts.permissions import IsBrandOwner
from accounts.serializers import LoginSerializer, ProfileUpdateSerializer
from accounts.services import auth_payload
from django.conf import settings
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Brand, Category, Product, ProductShareLink

from .serializers import (
    BrandOwnerSerializer,
    BrandRegisterSerializer,
    BrandSerializer,
    CategorySerializer,
    ProductSerializer,
    primary_brand_for,
)

logger = logging.getLogger(__name__)


class BrandRegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = BrandRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(auth_payload(user), status=status.HTTP_201_CREATED)


class BrandLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(
            data=request.data,
            context={"request": request, "expected_role": User.Role.PRODUCER},
        )
        serializer.is_valid(raise_exception=True)
        return Response(auth_payload(serializer.validated_data["user"]))


class BrandMeView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        return Response(
            BrandOwnerSerializer(request.user, context={"request": request}).data
        )

    def patch(self, request):
        serializer = ProfileUpdateSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        company_data = request.data.get("company")
        if company_data not in (None, ""):
            if not isinstance(company_data, dict):
                return Response(
                    {"company": "Enter company details as an object."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            brand = primary_brand_for(request.user, request)
            brand_serializer = BrandSerializer(
                brand,
                data=company_data,
                partial=brand is not None,
            )
            brand_serializer.is_valid(raise_exception=True)
            brand_serializer.save(owner=request.user)
        return Response(
            BrandOwnerSerializer(request.user, context={"request": request}).data
        )


class CategoryListView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        categories = Category.objects.all()
        return Response(CategorySerializer(categories, many=True).data)


class BrandListCreateView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        # The acting brand selects the company owner. Sibling brands under that
        # owner stay visible. Filtering to the acting id hid newly created brands.
        brands = Brand.objects.filter(owner=request.user).select_related("category")
        return Response(BrandSerializer(brands, many=True).data)

    def post(self, request):
        serializer = BrandSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(
                "Brand create rejected owner=%s errors=%s",
                getattr(request.user, "pk", None),
                serializer.errors,
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            brand = serializer.save(owner=request.user)
        except Exception:
            logger.exception("Brand create failed owner=%s", getattr(request.user, "pk", None))
            raise
        logger.info("Brand created id=%s owner=%s name=%s", brand.pk, brand.owner_id, brand.name)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class BrandDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def get_brand(self, request, pk):
        return get_object_or_404(Brand, pk=pk, owner=request.user)

    def get(self, request, pk):
        return Response(BrandSerializer(self.get_brand(request, pk)).data)

    def patch(self, request, pk):
        serializer = BrandSerializer(
            self.get_brand(request, pk),
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        self.get_brand(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductListCreateView(APIView):
    permission_classes = [IsBrandOwner]

    def get(self, request):
        products = (
            Product.objects.filter(brand__owner=request.user)
            .select_related("brand", "brand__category", "share_link")
            .prefetch_related("images", "demo_videos")
        )
        brand_id = request.query_params.get("brand")
        category_id = request.query_params.get("category")
        if brand_id:
            products = products.filter(brand_id=brand_id, brand__owner=request.user)
        if category_id:
            products = products.filter(brand__category_id=category_id)
        return Response(ProductSerializer(products, many=True).data)

    def post(self, request):
        data = request.data.copy()
        photos = request.FILES.getlist("photos")
        if photos:
            data.setlist("photos", photos)
        serializer = ProductSerializer(data=data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ProductDetailView(APIView):
    permission_classes = [IsBrandOwner]

    def get_product(self, request, pk):
        filters = {"pk": pk, "brand__owner": request.user}
        return get_object_or_404(
            Product.objects.select_related("brand", "brand__category", "share_link").prefetch_related(
                "images", "demo_videos"
            ),
            **filters,
        )

    def get(self, request, pk):
        return Response(ProductSerializer(self.get_product(request, pk)).data)

    def patch(self, request, pk):
        product = self.get_product(request, pk)
        data = request.data.copy()
        photos = request.FILES.getlist("photos")
        if photos:
            data.setlist("photos", photos)
        serializer = ProductSerializer(
            product,
            data=data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        self.get_product(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductShareView(APIView):
    permission_classes = [IsBrandOwner]

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk, brand__owner=request.user)
        link, _ = ProductShareLink.objects.get_or_create(
            product=product,
            defaults={"code": ProductShareLink.generate_code()},
        )
        ProductShareLink.objects.filter(pk=link.pk).update(
            share_count=F("share_count") + 1
        )
        link.refresh_from_db()
        origin = settings.SITE_URL.rstrip("/")
        share_url = f"{origin}/s/{link.code}"
        return Response(
            {
                "code": link.code,
                "url": share_url,
                "share_count": link.share_count,
                "open_count": link.open_count,
            }
        )


class ProductShareRedirectView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, code):
        from commerce.services.tracking import open_public_code

        return open_public_code(code, request)
