from __future__ import annotations

from django.db import models


class QueueLog(models.Model):
    time = models.DateTimeField()
    callid = models.CharField(max_length=255)
    queuename = models.CharField(max_length=128)
    agent = models.CharField(max_length=128)
    event = models.CharField(max_length=64)
    data1 = models.CharField(max_length=255, blank=True, null=True)
    data2 = models.CharField(max_length=255, blank=True, null=True)
    data3 = models.CharField(max_length=255, blank=True, null=True)
    data4 = models.CharField(max_length=255, blank=True, null=True)
    data5 = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = "queuelog"
        ordering = ["-time"]


class AgentsNew(models.Model):
    agent = models.CharField(primary_key=True, max_length=128)
    name = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = True
        db_table = "agents_new"
        verbose_name = "Agent"
        verbose_name_plural = "Agents"


class QueuesNew(models.Model):
    queuename = models.CharField(primary_key=True, max_length=128)
    descr = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = True
        db_table = "queues_new"
        verbose_name = "Queue"
        verbose_name_plural = "Queues"


class QueueMemberTable(models.Model):
    queue_name = models.CharField(max_length=128)
    interface = models.CharField(max_length=255)
    penalty = models.IntegerField()
    paused = models.BooleanField()
    member_name = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = "queue_members"


class Cdr(models.Model):
    calldate = models.DateTimeField()
    clid = models.CharField(max_length=80)
    src = models.CharField(max_length=80)
    dst = models.CharField(max_length=80)
    dcontext = models.CharField(max_length=80)
    channel = models.CharField(max_length=80)
    dstchannel = models.CharField(max_length=80)
    lastapp = models.CharField(max_length=80)
    lastdata = models.CharField(max_length=80)
    duration = models.IntegerField()
    billsec = models.IntegerField()
    disposition = models.CharField(max_length=45)
    amaflags = models.IntegerField()
    accountcode = models.CharField(max_length=20)
    uniqueid = models.CharField(max_length=32)
    userfield = models.CharField(max_length=255)
    recordingfile = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        managed = False
        db_table = "cdr"


class CallTranscription(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    callid = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    text = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "call_transcriptions"
        ordering = ["-updated_at"]


class ProductEvent(models.Model):
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_events",
    )
    event_name = models.CharField(max_length=64, db_index=True)
    page = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        managed = True
        db_table = "product_events"
        ordering = ["-created_at"]
