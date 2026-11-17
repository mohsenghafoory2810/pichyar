from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from notifications import services, tasks
from notifications.models import SMSCampaign, SMSLog
from notifications.providers import SMSResult

from .test_sms import KAVENEGAR_SEND, use_kavenegar

S = SMSLog.Status
C = SMSCampaign.Status
User = get_user_model()


class CampaignTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("09120000001", password="pass")
        User.objects.create_user("09121111111")
        User.objects.create_user("09122222222")
        User.objects.create_user("09123333333", is_active=False)

    def test_recipients_are_active_users(self):
        self.assertEqual(
            list(services.campaign_recipients()), ["09120000001", "09121111111", "09122222222"]
        )

    def test_validation_of_placeholders(self):
        campaign = SMSCampaign(text="تخفیف {code}")
        with self.assertRaisesMessage(ValidationError, "{code}"):
            campaign.full_clean()
        campaign.text = "تخفیف ویژهٔ {site_name}"
        campaign.full_clean()
        campaign.text = "   "
        with self.assertRaises(ValidationError):
            campaign.full_clean()

    def test_console_mode_sends_at_once(self):
        campaign = SMSCampaign.objects.create(text="حراج {site_name}\n{site_url}")
        with self.captureOnCommitCallbacks(execute=True):
            services.start_campaign(campaign)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, C.DONE)
        self.assertEqual(campaign.recipients_count, 3)
        logs = campaign.logs.all()
        self.assertEqual(logs.count(), 3)
        self.assertTrue(all(log.status == S.SENT for log in logs))
        self.assertEqual(logs[0].text, "حراج پیچ‌یار\nhttps://pichyar.ir")

    def test_kavenegar_sends_in_batches_through_the_worker(self):
        use_kavenegar()
        campaign = SMSCampaign.objects.create(text="سلام")
        with mock.patch("django_q.tasks.async_task") as async_task, self.captureOnCommitCallbacks(execute=True):
            services.start_campaign(campaign)
        async_task.assert_called_once_with("notifications.tasks.prepare_campaign", campaign.pk)

        with mock.patch.object(services, "CAMPAIGN_BATCH", 2), mock.patch("django_q.tasks.async_task") as async_task:
            self.assertEqual(tasks.prepare_campaign(campaign.pk), 3)
        batches = [c.args[1] for c in async_task.call_args_list]
        self.assertEqual([len(b) for b in batches], [2, 1])
        self.assertEqual(tasks.prepare_campaign(campaign.pk), 0)  # never prepared twice
        self.assertEqual(SMSLog.objects.filter(campaign=campaign).count(), 3)

        with mock.patch(KAVENEGAR_SEND, return_value=SMSResult(message_id="1")) as send:
            for batch in batches:
                tasks.deliver_sms_batch(batch)
            tasks.deliver_sms_batch(batches[0])  # already sent: skipped
        self.assertEqual(send.call_count, 3)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, C.DONE)

    def test_lost_campaign_is_picked_up_by_the_retry_job(self):
        use_kavenegar()
        campaign = SMSCampaign.objects.create(text="سلام")
        SMSCampaign.objects.filter(pk=campaign.pk).update(created_at=campaign.created_at - services.LOST_JOB_AFTER * 2)
        with mock.patch("django_q.tasks.async_task") as async_task:
            tasks.retry_pending_sms()
        self.assertEqual(SMSLog.objects.filter(campaign=campaign).count(), 3)
        self.assertEqual(async_task.call_args.args[0], "notifications.tasks.deliver_sms_batch")
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, C.SENDING)

    def test_admin_add_needs_confirmation_and_sends(self):
        self.client.force_login(self.admin)
        url = reverse("admin:notifications_smscampaign_add")
        response = self.client.get(url)
        self.assertContains(response, "3 کاربر فعال")
        response = self.client.post(url, {"text": "حراج"})
        self.assertContains(response, "تیک بزنید")
        self.assertFalse(SMSCampaign.objects.exists())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {"text": "حراج", "confirm": "on"})
        self.assertEqual(response.status_code, 302)
        campaign = SMSCampaign.objects.get()
        self.assertEqual(campaign.created_by, self.admin)
        self.assertEqual(campaign.logs.filter(status=S.SENT).count(), 3)

        for page in (
            reverse("admin:notifications_smscampaign_changelist"),
            reverse("admin:notifications_smscampaign_change", args=[campaign.pk]),
            reverse("admin:notifications_smslog_changelist") + f"?campaign__id__exact={campaign.pk}",
        ):
            with self.subTest(page=page):
                self.assertEqual(self.client.get(page).status_code, 200)
        # sent campaigns are read-only and cannot be deleted
        response = self.client.post(
            reverse("admin:notifications_smscampaign_change", args=[campaign.pk]), {"text": "دیگر"}
        )
        self.assertEqual(response.status_code, 403)
        campaign.refresh_from_db()
        self.assertEqual(campaign.text, "حراج")
        self.assertEqual(
            self.client.post(reverse("admin:notifications_smscampaign_delete", args=[campaign.pk])).status_code, 403
        )
