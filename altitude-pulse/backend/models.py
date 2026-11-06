"""Public request contracts. Prices and loyalty are never accepted from clients."""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RequestModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class UserCreate(RequestModel):
    name: str = Field(min_length=1, max_length=60)
    phone_number: str = Field(min_length=7, max_length=24)

    @field_validator('phone_number')
    @classmethod
    def normalize_phone(cls, value):
        if not re.fullmatch(r'\+?[\d ()-]+', value):
            raise ValueError('Use a phone number with digits and an optional country prefix')
        value = re.sub(r'[^\d+]', '', value)
        if not 7 <= len(value.lstrip('+')) <= 15:
            raise ValueError('Phone numbers must contain 7 to 15 digits')
        return value


class OrderLine(RequestModel):
    item_id: int = Field(gt=0)
    item_size: Literal['12oz', '16oz', 'Standard'] = '16oz'
    customization: str = Field(default='', max_length=200)


class OrderCreate(RequestModel):
    user_id: int = Field(gt=0)
    customer_name: str = Field(min_length=1, max_length=60)
    order_type: Literal['takeaway', 'table'] = 'takeaway'
    table_number: str | None = Field(default=None, max_length=12)
    items: list[OrderLine] = Field(min_length=1, max_length=26)
    payment_method: Literal['card', 'apple_pay'] = 'card'
    promo_token: str | None = Field(default=None, max_length=128)

    @model_validator(mode='after')
    def validate_table(self):
        if self.order_type == 'table' and not self.table_number:
            raise ValueError('A table number is required for table orders')
        if self.order_type == 'takeaway':
            self.table_number = None
        return self


class StatusUpdate(RequestModel):
    order_id: int = Field(gt=0)
    status: Literal['preparing', 'ready', 'completed', 'cancelled']


class RSVPCreate(RequestModel):
    user_id: int = Field(gt=0)
