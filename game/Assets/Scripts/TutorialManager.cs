using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class TutorialManager : MonoBehaviour
{
    public static readonly string TAG = "TutorialManager";
    private static readonly string CANVAS_TAG = "TOOLTIP_CANVAS";
    private static TutorialManager _instance;

    public GameObject TooltipTextbox;
    public GameObject HighlightBox;

    public float HighlightPadding = 0.5f;

    private Prop _indicator = null;

    private Network.Tooltip _lastTooltip = null;

    private Logger _logger = null;

    public static TutorialManager TaggedInstance()
    {
        if (_instance == null)
        {
            GameObject tutorialManager = GameObject.FindGameObjectWithTag(TutorialManager.TAG);
            _instance = tutorialManager.GetComponent<TutorialManager>();
        }
        return _instance;
    }

    private Canvas TaggedCanvas()
    {
        Canvas canvas = GameObject.FindGameObjectWithTag(CANVAS_TAG).GetComponent<Canvas>();
        return canvas;
    }

    public void SetIndicator(HecsCoord location)
    {
        if (_indicator != null)
        {
            _indicator.Destroy();
        }
        UnityAssetSource assetSource = new UnityAssetSource();
        IAssetSource.AssetId assetId = IAssetSource.AssetId.TUTORIAL_INDICATOR;
        GameObject groundPulse = assetSource.Load(assetId);
        _indicator = new Prop(groundPulse, assetId);
        _indicator.AddAction(Init.InitAt(location, 0));
    }

    public void ClearIndicator()
    {
        if (_indicator != null)
        {
            _indicator.Destroy();
        }
    }

    public void OverlayRectangle(RectTransform overlay, RectTransform uiElement)
    {
        // Get the coordinates (corners) of uiElement in world space.
        Vector3[] corners = new Vector3[4];
        uiElement.GetWorldCorners(corners);

        _logger.Info("uiElement: world corners: " + corners[0] + ", " + corners[1] + ", " + corners[2] + ", " + corners[3]);


        // Convert the coordinates to screen space.
        Vector3[] screenCorners = new Vector3[4];
        for (int i = 0; i < 4; i++)
        {
            screenCorners[i] = RectTransformUtility.WorldToScreenPoint(Camera.main, corners[i]);
        }

        _logger.Info("uiElement: screen corners: " + screenCorners[0] + ", " + screenCorners[1] + ", " + screenCorners[2] + ", " + screenCorners[3]);

        // Calculate the minimum and maximum x and y values.
        float minX = Mathf.Min(screenCorners[0].x, screenCorners[1].x, screenCorners[2].x, screenCorners[3].x);
        float maxX = Mathf.Max(screenCorners[0].x, screenCorners[1].x, screenCorners[2].x, screenCorners[3].x);
        float minY = Mathf.Min(screenCorners[0].y, screenCorners[1].y, screenCorners[2].y, screenCorners[3].y);
        float maxY = Mathf.Max(screenCorners[0].y, screenCorners[1].y, screenCorners[2].y, screenCorners[3].y);

        _logger.Info("uiElement: minX: " + minX + ", maxX: " + maxX + ", minY: " + minY + ", maxY: " + maxY);

        // Calculate the width and height of the overlay.
        float width = maxX - minX;
        float height = maxY - minY;

        // Set the pivot and anchor to 0.
        overlay.pivot = new Vector2(0, 0);
        overlay.anchorMin = new Vector2(0, 0);
        overlay.anchorMax = new Vector2(0, 0);

        // Set the position and size of the overlay.
        overlay.anchoredPosition = new Vector2(minX - HighlightPadding / 2.0f, minY - HighlightPadding / 2.0f);
        overlay.sizeDelta = new Vector2(width + HighlightPadding, height + HighlightPadding);

    }

    public void SetTooltip(string text, string highlightedComponentTag)
    {
        Canvas canvas = TaggedCanvas();
        float canvasWidth = canvas.GetComponent<RectTransform>().rect.width;
        float canvasHeight = canvas.GetComponent<RectTransform>().rect.height;
        TMPro.TMP_Text tooltip = TooltipTextbox.GetComponent<TMPro.TMP_Text>();
        tooltip.text = text;
        if (highlightedComponentTag == "")
        {
            HighlightBox.GetComponent<RectTransform>().sizeDelta = new Vector2(0, 0);
            return;
        }
        _logger.Info("Highlighted component tag: " + highlightedComponentTag);
        GameObject highlightedComponent = GameObject.FindGameObjectWithTag(highlightedComponentTag);

        if (highlightedComponent == null)
        {
            _logger.Warn("Could not find highlighted component with tag: " + highlightedComponentTag);
            HighlightBox.GetComponent<RectTransform>().sizeDelta = new Vector2(0, 0);
            return;
        }

        RectTransform highlightedComponentRect = highlightedComponent.GetComponent<RectTransform>();

        if (highlightedComponentRect == null)
        {
            _logger.Warn("Highlighted component with tag \"" + highlightedComponentTag + "\" has no RectTransform");
            return;
        }

        OverlayRectangle(HighlightBox.GetComponent<RectTransform>(), highlightedComponentRect);
        HighlightBox.GetComponent<RectTransform>().ForceUpdateRectTransforms();
    }

    public void HandleTutorialStep(Network.TutorialStep step)
    {
        if (step.tooltip != null)
        {
            Network.Tooltip tooltip = step.tooltip;
            _lastTooltip = tooltip;
            SetTooltip(tooltip.text, tooltip.highlighted_component_tag);
        }
        if (step.indicator != null)
        {
            SetIndicator(step.indicator.location);
        } else {
            ClearIndicator();
        }
    }

    public void NextStep()
    {
        Network.NetworkManager.TaggedInstance().NextTutorialStep();
    }

    public void Start()
    {
        _logger = Logger.GetOrCreateTrackedLogger("TutorialManager");
        NextStep();
    }

    public void Update()
    {
        if (_lastTooltip != null)
        {
            if ((Input.GetKeyDown(KeyCode.LeftShift) || Input.GetKeyDown(KeyCode.RightShift)) && (_lastTooltip.type == Network.TooltipType.UNTIL_DISMISSED))
            {
                NextStep();
            }
            if (Input.GetKeyDown(KeyCode.C) && (_lastTooltip.type == Network.TooltipType.UNTIL_CAMERA_TOGGLED))
            {
                NextStep();
            }
        }
        if (_indicator != null)
        {
            _indicator.Update();
        }
    }
}
